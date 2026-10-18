"""Wiring: builds providers and services from settings. Views depend on these factories,
and tests override them with fakes."""

import logging
from datetime import timedelta
from functools import cache

import httpx
from django.conf import settings
from django.core.cache import cache as django_cache
from django.core.exceptions import ImproperlyConfigured

from planner.providers.fallback import FallbackGeocoder
from planner.providers.nws import NwsWeather
from planner.providers.openmeteo import OpenMeteoWeather
from planner.providers.photon import PhotonGeocoder
from planner.providers.tomtom import TomTomRouting
from planner.providers.tomtom_search import TomTomGeocoder
from planner.providers.weatherapi import WeatherApiWeather
from planner.services.heatmap import HeatmapBuilder
from planner.services.plan_trip import TripPlanner
from planner.services.routing import CachedRouting
from planner.services.weather import WeatherService

log = logging.getLogger(__name__)

USER_AGENT = "truck-weather-routing/1.0 (+https://github.com/murtuza777/spotter_labs_assessment)"


@cache
def http_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS, connect=5.0),
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


def weather_providers() -> list:
    """The configured provider chain; a provider without its required key is left out."""
    available = {
        "open-meteo": lambda: OpenMeteoWeather(
            http_client(),
            base_url=settings.OPEN_METEO_BASE_URL or None,
            api_key=settings.OPEN_METEO_API_KEY,
            model=settings.WEATHER_MODEL,
            batch_size=settings.WEATHER_BATCH_SIZE,
            max_workers=settings.WEATHER_MAX_WORKERS,
        ),
        "nws": lambda: NwsWeather(
            http_client(),
            django_cache,
            user_agent=settings.NWS_USER_AGENT or USER_AGENT,
            max_workers=settings.NWS_MAX_WORKERS,
            point_ttl_s=settings.NWS_POINT_TTL_S,
            grid_ttl_s=settings.NWS_GRID_TTL_S,
            max_age=timedelta(hours=settings.NWS_MAX_AGE_H),
        ),
        "weatherapi": lambda: (
            WeatherApiWeather(
                http_client(),
                api_key=settings.WEATHERAPI_KEY,
                days=settings.WEATHERAPI_DAYS,
                max_workers=settings.WEATHERAPI_MAX_WORKERS,
            )
            if settings.WEATHERAPI_KEY
            else None
        ),
    }
    chain = []
    for name in settings.WEATHER_PROVIDERS:
        if name not in available:
            raise ImproperlyConfigured(f"Unknown weather provider {name!r} in WEATHER_PROVIDERS")
        provider = available[name]()
        if provider is None:
            log.warning("weather provider %s skipped: no API key configured", name)
        else:
            chain.append(provider)
    if not chain:
        raise ImproperlyConfigured("No usable weather provider is configured")
    return chain


@cache
def weather_service() -> WeatherService:
    return WeatherService(
        weather_providers(),
        django_cache,
        grid_deg=settings.WEATHER_GRID_DEG,
        ttl_s=settings.WEATHER_CACHE_TTL_S,
        model=settings.WEATHER_MODEL,
    )


@cache
def trip_planner() -> TripPlanner:
    routing = CachedRouting(
        TomTomRouting(settings.TOMTOM_API_KEY, http_client()),
        django_cache,
        ttl_s=settings.ROUTE_CACHE_TTL_S,
    )
    return TripPlanner(routing, weather_service(), tare_lb=settings.TRUCK_TARE_LB)


@cache
def heatmap_builder() -> HeatmapBuilder:
    return HeatmapBuilder(weather_service(), max_points=settings.HEATMAP_MAX_POINTS)


@cache
def geocoder() -> FallbackGeocoder:
    available = {
        "photon": lambda: PhotonGeocoder(http_client(), base_url=settings.PHOTON_BASE_URL),
        "tomtom": lambda: TomTomGeocoder(settings.TOMTOM_API_KEY, http_client()),
    }
    return FallbackGeocoder([(name, available[name]()) for name in settings.GEOCODER_ORDER])
