# Risk model and ranking

The rules come from the assessment brief. The code is [`domain/risk.py`](../backend/planner/domain/risk.py), [`domain/scoring.py`](../backend/planner/domain/scoring.py) and [`domain/recommend.py`](../backend/planner/domain/recommend.py), and every edge below is pinned by a unit test (`test_risk.py`, `test_recommend.py`).

## 1. Rule table

Each checkpoint is classified separately for wind, rain and snow, at the forecast hour the truck reaches it.

| Level (score) | Wind (mph) | Rain (in/hr) | Snow (in/hr) |
|---|---|---|---|
| Low (0) | < 25 | < 0.10 | < 0.5 |
| Moderate (1) | 25 – < 35 | 0.10 – < 0.25 | 0.5 – < 1.0 |
| High (2) | 35 – < 45 | 0.25 – < 0.50 | 1.0 – < 2.0 |
| Severe (3) | 45 – < 55 | 0.50 – 1.00 | 2.0 – 3.0 |
| No Travel (4) | ≥ 55 | > 1.00 | > 3.0 |

**Load rules** apply to wind only:

| Wind level | Load | Result |
|---|---|---|
| Severe (45–54 mph) | > 30,000 lb | No Travel |
| High (35–44 mph) | > 40,000 lb | Severe |

**Checkpoint risk** is the worst of the wind level (after the load rules), the rain level and the snow level. Each checkpoint also keeps a plain-language reason, for example *"Gusts 47 mph with load 36,000 lb > 30,000 lb: Severe raised to No Travel"*.

## 2. Interpretations

The brief leaves some cases open. These are the choices made, each covered by tests.

| Topic | Decision |
|---|---|
| **Band edges** | Bands are half-open with the lower bound inclusive, so a value on a shared edge goes to the higher level: 25 mph is Moderate, and rain of 0.25 in/hr is High. The brief writes No Travel as "> 1.00" and "> 3.0", so rain of exactly 1.00 in/hr and snow of exactly 3.0 in/hr stay Severe. The wind band "25–34" is read as continuous, so 34.6 mph is Moderate. |
| **Load threshold** | "Over 30,000 lb" is strict: 30,000 lb doesn't escalate, and 30,001 lb does. The same applies at 40,000 lb. |
| **Which wind** | **Gusts** by default, because gusts are what blow over high-profile trailers. The form can switch the rules to sustained wind; both readings are always shown. |
| **Rain** | An hourly intensity in in/hr, never a probability of precipitation. Where a provider doesn't split rain from snow, all precipitation counts as rain, which can only overstate the risk. |
| **Forecast hour** | Every value is normalized to the hour **ending** at its timestamp. A truck passing at 14:20 is inside 14:00–15:00, so it uses the 15:00 value (the ETA rounded up). Where a provider doesn't document which hour a value covers, the worse of the two neighbouring hours is used. |
| **Miles per level** | Each checkpoint owns the stretch from the midpoint with the previous checkpoint to the midpoint with the next. The first starts at mile 0, and the last ends at the destination. The shares add up exactly to the route length. |
| **Average risk** | Miles-weighted mean of the scores 0–4 over the miles that have a forecast |
| **Routing weight** | TomTom gets the gross weight: the load plus a 35,000 lb empty tractor-trailer. The risk rules use the load as entered. |
| **ETAs** | From TomTom's travel time at each point along the route, so city stretches are slow and interstates fast. Hours-of-service breaks aren't modeled. |

## 3. Recommendation

**Ranking:** exactly the brief's order, and nothing else:

1. Fewest **Severe** miles
2. Fewest **High** miles
3. Lowest **average risk**
4. Shortest **drive time**

Ties are judged at a fixed precision: miles at 0.1 mi and average risk at 0.01. That way float noise counts as a tie and the next criterion decides. Drive time only matters once the risk criteria are equal, so a faster route can never beat one with fewer Severe miles. The order TomTom returned routes in decides only a complete tie on all four criteria; otherwise the result is the same for every input order (tested over every permutation).

**Eligibility constraint:** applied *before* ranking. These are safety rules, not extra ranking criteria:

| Route condition | Effect |
|---|---|
| Any **No Travel** miles | Not eligible, so never recommended. It's still shown and ranked after the eligible routes, with the reason. |
| Some miles **without a forecast** | It can't be confirmed safe. It's not eligible while a fully forecast route without No Travel exists. If no route is fully forecast, the best one with at least 50 % coverage is a clearly labeled **provisional pick**. |
| Less than **50 %** forecast coverage | Too little data to assess |
| Every route has No Travel | **Nothing is recommended**: "No safe route at this departure time", with each route's No Travel miles |
| No route has enough forecast | **Nothing is recommended**: "Weather unavailable: no route can be assessed", with each provider's failure reason |

**Explanation:** the reason sentence compares the pick with *every* other eligible route on the first criterion that separates them. For example: *"Route B beats Route C on travel time (8h 01m vs 8h 58m) and Route A on average risk (0.00 vs 0.14)."*

## 4. Missing weather

A checkpoint is **unknown** when any of its four values (sustained wind, gusts, rain, snow) is missing, invalid, negative or NaN, or when the hour is outside the forecast. Unknown is never treated as Low:

- **Scoring:** its miles aren't scored, and they count against the route's forecast coverage.
- **Map:** shown as a hollow grey ring on the map, a dashed grey stretch of the route, and a hatched part of the route card's miles bar, labeled "No forecast".
- **Heatmap:** grey dots mark grid cells with no forecast for the selected hour.

## 5. Worked example

The load is 36,000 lb, using gusts. A checkpoint reached at 14:20 uses the forecast hour ending 15:00:

| Factor | Reading | Table level | After load rules |
|---|---|---|---|
| Gusts | 47 mph | Severe | **No Travel** (load > 30,000 lb) |
| Rain | 0.12 in/hr | Moderate | Moderate |
| Snow | 0.0 in/hr | Low | Low |

The checkpoint is **No Travel**, the worst factor. Its owned miles, say 25, go to the route's No Travel miles. The route is therefore not eligible, and it can't be recommended, whatever its drive time.
