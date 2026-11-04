"""Bengaluru pickup areas (approximate coordinates) used by the form and the NLP parser."""

AREAS = [
    {"name": "MG Road", "lat": 12.975600, "lon": 77.605000, "aliases": ["mg road", "m g road", "mahatma gandhi road"]},
    {"name": "Jayanagar", "lat": 12.929900, "lon": 77.582600, "aliases": []},
    {"name": "Hebbal", "lat": 13.035800, "lon": 77.597000, "aliases": []},
    {"name": "Whitefield", "lat": 12.969800, "lon": 77.750000, "aliases": []},
    {"name": "Malleshwaram", "lat": 13.003100, "lon": 77.564300, "aliases": ["malleswaram"]},
    {"name": "Electronic City", "lat": 12.845200, "lon": 77.660200, "aliases": ["ecity", "e city", "e-city"]},
    {"name": "Indiranagar", "lat": 12.978400, "lon": 77.640800, "aliases": ["indira nagar"]},
    {"name": "Koramangala", "lat": 12.935200, "lon": 77.624500, "aliases": []},
    {"name": "BTM Layout", "lat": 12.916600, "lon": 77.610100, "aliases": ["btm"]},
    {"name": "HSR Layout", "lat": 12.911600, "lon": 77.647400, "aliases": ["hsr"]},
    {"name": "Banashankari", "lat": 12.925500, "lon": 77.546800, "aliases": []},
    {"name": "Rajajinagar", "lat": 12.998200, "lon": 77.553000, "aliases": []},
    {"name": "Yelahanka", "lat": 13.100700, "lon": 77.596300, "aliases": []},
    {"name": "Marathahalli", "lat": 12.956900, "lon": 77.701100, "aliases": []},
    {"name": "Yeshwanthpur", "lat": 13.028500, "lon": 77.540000, "aliases": ["yeshwantpur"]},
    {"name": "Majestic", "lat": 12.976700, "lon": 77.571300, "aliases": ["kempegowda bus station"]},
    {"name": "Bellandur", "lat": 12.930400, "lon": 77.678400, "aliases": []},
    {"name": "JP Nagar", "lat": 12.906300, "lon": 77.585700, "aliases": ["jp nagar", "j p nagar"]},
]

BY_NAME = {a["name"]: a for a in AREAS}
