"""Wiring: builds providers and services from settings. Views depend on these factories,
and tests override them with fakes."""

from functools import cache

import httpx
from django.conf import settings
from django.core.cache import cache as django_cache

from planner.providers.fallback import FallbackGeocoder
from planner.providers.openmeteo import OpenMeteoWeather
from planner.providers.photon import PhotonGeocoder
from planner.providers.tomtom import TomTomRouting
from planner.providers.tomtom_search import TomTomGeocoder
from planner.services.heatmap import HeatmapBuilder
from planner.services.plan_trip import TripPlanner
from planner.services.routing import CachedRouting
from planner.services.weather import WeatherService

USER_AGENT = "truck-weather-routing/1.0 (+https://github.com/murtuza777/spotter_labs_assessment)"


@cache
def http_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(settings.HTTP_TIMEOUT_SECONDS, connect=5.0),
        headers={"User-Agent": USER_AGENT},
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )


@cache
def weather_service() -> WeatherService:
    provider = OpenMeteoWeather(
        http_client(),
        base_url=settings.OPEN_METEO_BASE_URL,
        model=settings.WEATHER_MODEL,
        batch_size=settings.WEATHER_BATCH_SIZE,
        max_workers=settings.WEATHER_MAX_WORKERS,
    )
    return WeatherService(
        provider,
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
