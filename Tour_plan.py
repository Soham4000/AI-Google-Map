import streamlit as st
import requests
import google.generativeai as genai
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
from datetime import date
import math


# ============================================================
# PAGE CONFIGURATION
# ============================================================

st.set_page_config(
    page_title="AI Travel & Movie Planner",
    page_icon="✈️",
    layout="wide"
)


# ============================================================
# API CONFIGURATION
# ============================================================

try:
    api_key = st.secrets["GEMINI_API_KEY"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_MAP_API_KEY"]

    genai.configure(api_key=api_key)

except Exception:
    st.error(
        "❌ API keys not found.\n\n"
        "Please add GEMINI_API_KEY and GOOGLE_MAP_API_KEY "
        "to your Streamlit secrets."
    )
    st.stop()


# ============================================================
# GEMINI MODEL
# ============================================================

model = genai.GenerativeModel("gemini-3.8-flash")


# ============================================================
# SESSION STATE
# ============================================================

if "show_result" not in st.session_state:
    st.session_state.show_result = False


# ============================================================
# PAGE TITLE
# ============================================================

st.title("✈️ AI Travel & Movie Planner")

st.write(
    "Plan your trip with AI-powered travel recommendations, "
    "hotels, personalized itineraries and mood-based movie suggestions."
)


# ============================================================
# GOOGLE POLYLINE DECODER
# ============================================================

def decode_polyline(encoded):

    points = []

    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):

        # ----------------------------------------------------
        # LATITUDE
        # ----------------------------------------------------

        shift = 0
        result = 0

        while True:

            byte = ord(encoded[index]) - 63
            index += 1

            result |= (byte & 0x1F) << shift
            shift += 5

            if byte < 0x20:
                break

        if result & 1:
            dlat = ~(result >> 1)
        else:
            dlat = result >> 1

        lat += dlat

        # ----------------------------------------------------
        # LONGITUDE
        # ----------------------------------------------------

        shift = 0
        result = 0

        while True:

            byte = ord(encoded[index]) - 63
            index += 1

            result |= (byte & 0x1F) << shift
            shift += 5

            if byte < 0x20:
                break

        if result & 1:
            dlng = ~(result >> 1)
        else:
            dlng = result >> 1

        lng += dlng

        points.append(
            [
                lat / 100000.0,
                lng / 100000.0
            ]
        )

    return points


# ============================================================
# GET GOOGLE ROUTE
# ============================================================

def get_google_route(
    source_lat,
    source_lon,
    destination_lat,
    destination_lon,
    mode="driving",
    transit_mode=None
):

    url = (
        "https://maps.googleapis.com/maps/api/"
        "directions/json"
    )

    params = {
        "origin": f"{source_lat},{source_lon}",
        "destination": f"{destination_lat},{destination_lon}",
        "key": GOOGLE_API_KEY,
        "mode": mode,
        "alternatives": "false"
    }

    if mode == "transit" and transit_mode:

        params["transit_mode"] = transit_mode

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        data = response.json()

        if data.get("status") != "OK":

            return (
                None,
                data.get(
                    "status",
                    "UNKNOWN_ERROR"
                ),
                None
            )

        routes = data.get("routes", [])

        if not routes:

            return None, "NO_ROUTE", None

        route = routes[0]

        legs = route.get("legs", [])

        # ------------------------------------------------
        # Build the path by stitching together every
        # step's own polyline, instead of only the coarse
        # overview polyline. This hugs every turn on the
        # actual road, the same way Google Maps itself
        # draws a route.
        # ------------------------------------------------

        coordinates = []

        for leg in legs:

            for step in leg.get("steps", []):

                step_polyline = (
                    step
                    .get("polyline", {})
                    .get("points")
                )

                if not step_polyline:

                    continue

                step_coords = decode_polyline(
                    step_polyline
                )

                if coordinates and step_coords:

                    # Drop the first point of each new
                    # step, since it duplicates the last
                    # point of the previous step.

                    step_coords = step_coords[1:]

                coordinates.extend(step_coords)

        if not coordinates:

            overview = route.get(
                "overview_polyline",
                {}
            )

            encoded = overview.get("points")

            if not encoded:

                return None, "NO_POLYLINE", None

            coordinates = decode_polyline(encoded)

        duration_text = None

        if legs:

            duration_text = (
                legs[0]
                .get("duration", {})
                .get("text")
            )

        return coordinates, "OK", duration_text

    except Exception as e:

        return None, str(e), None


# ============================================================
# FLIGHT PATH
# ============================================================

def create_flight_path(
    lat1,
    lon1,
    lat2,
    lon2,
    number_of_points=100
):

    """
    Creates a curved great-circle style path for flights.
    """

    lat1 = math.radians(lat1)
    lon1 = math.radians(lon1)

    lat2 = math.radians(lat2)
    lon2 = math.radians(lon2)

    x1 = math.cos(lat1) * math.cos(lon1)
    y1 = math.cos(lat1) * math.sin(lon1)
    z1 = math.sin(lat1)

    x2 = math.cos(lat2) * math.cos(lon2)
    y2 = math.cos(lat2) * math.sin(lon2)
    z2 = math.sin(lat2)

    dot = (
        x1 * x2 +
        y1 * y2 +
        z1 * z2
    )

    dot = max(-1.0, min(1.0, dot))

    omega = math.acos(dot)

    if abs(omega) < 0.000001:

        return [
            [
                math.degrees(lat1),
                math.degrees(lon1)
            ],
            [
                math.degrees(lat2),
                math.degrees(lon2)
            ]
        ]

    points = []

    sin_omega = math.sin(omega)

    for i in range(number_of_points + 1):

        t = i / number_of_points

        a = (
            math.sin((1 - t) * omega)
            / sin_omega
        )

        b = (
            math.sin(t * omega)
            / sin_omega
        )

        x = a * x1 + b * x2
        y = a * y1 + b * y2
        z = a * z1 + b * z2

        lat = math.atan2(
            z,
            math.sqrt(x * x + y * y)
        )

        lon = math.atan2(y, x)

        points.append(
            [
                math.degrees(lat),
                math.degrees(lon)
            ]
        )

    return points


# ============================================================
# FREE FALLBACK ROUTE (NO API KEY NEEDED)
# ============================================================
#
# If Google Directions fails (key not enabled, no
# billing, quota, etc.) this uses the free public OSRM
# routing server so a real, road-following line can
# still be drawn without requiring any API key at all.
# ============================================================

def get_osrm_route(
    source_lat,
    source_lon,
    destination_lat,
    destination_lon,
    profile="driving"
):

    url = (
        "https://router.project-osrm.org/route/v1/"
        f"{profile}/"
        f"{source_lon},{source_lat};"
        f"{destination_lon},{destination_lat}"
    )

    params = {
        "overview": "full",
        "geometries": "geojson"
    }

    try:

        response = requests.get(
            url,
            params=params,
            timeout=30
        )

        data = response.json()

        if data.get("code") != "Ok":

            return (
                None,
                data.get("code", "OSRM_ERROR"),
                None
            )

        routes = data.get("routes", [])

        if not routes:

            return None, "NO_ROUTE", None

        route = routes[0]

        geometry = route.get("geometry", {})

        raw_coordinates = geometry.get(
            "coordinates",
            []
        )

        # OSRM returns [lon, lat] pairs, folium/leaflet
        # need [lat, lon].

        coordinates = [
            [point[1], point[0]]
            for point in raw_coordinates
        ]

        duration_seconds = route.get("duration")

        duration_text = None

        if duration_seconds is not None:

            total_minutes = round(
                duration_seconds / 60
            )

            if total_minutes < 60:

                duration_text = f"{total_minutes} min"

            else:

                hours = total_minutes // 60
                minutes = total_minutes % 60

                duration_text = (
                    f"{hours} hr {minutes} min"
                )

        return coordinates, "OK", duration_text

    except Exception as e:

        return None, str(e), None


# ============================================================
# ROUTE BASED ON TRANSPORT
# ============================================================

def get_transport_route(
    source_lat,
    source_lon,
    destination_lat,
    destination_lon,
    transport
):

    coordinates = None
    status = None
    duration_text = None

    osrm_profile = None


    # --------------------------------------------------------
    # CAR
    # --------------------------------------------------------

    if transport == "Car":

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="driving"
            )
        )

        osrm_profile = "driving"


    # --------------------------------------------------------
    # BUS
    # --------------------------------------------------------

    elif transport == "Bus":

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="transit",
                transit_mode="bus"
            )
        )

        # Buses run on roads, so a driving path is a
        # reasonable stand-in when transit data is
        # unavailable for this route.

        osrm_profile = "driving"


    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

    elif transport == "Train":

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="transit",
                transit_mode="train"
            )
        )

        # Trains run on rail, not roads, so there is no
        # sensible OSRM road profile to fall back on.

        osrm_profile = None


    # --------------------------------------------------------
    # WALKING
    # --------------------------------------------------------

    elif transport == "Walking":

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="walking"
            )
        )

        osrm_profile = "walking"


    # --------------------------------------------------------
    # BICYCLE
    # --------------------------------------------------------

    elif transport == "Bicycle":

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="bicycling"
            )
        )

        osrm_profile = "cycling"


    # --------------------------------------------------------
    # FLIGHT
    # --------------------------------------------------------

    elif transport == "Flight":

        coordinates = create_flight_path(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon
        )

        return coordinates, "OK", None


    # --------------------------------------------------------
    # DEFAULT
    # --------------------------------------------------------

    else:

        coordinates, status, duration_text = (
            get_google_route(
                source_lat,
                source_lon,
                destination_lat,
                destination_lon,
                mode="driving"
            )
        )

        osrm_profile = "driving"


    # ----------------------------------------------------
    # FALLBACK 1: FREE OSRM ROUTING, NO API KEY NEEDED.
    # Used only when Google Directions did not return a
    # usable path.
    # ----------------------------------------------------

    if not coordinates and osrm_profile:

        (
            osrm_coordinates,
            osrm_status,
            osrm_duration_text
        ) = get_osrm_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            profile=osrm_profile
        )

        if osrm_coordinates:

            return (
                osrm_coordinates,
                "OK_FALLBACK_OSRM",
                osrm_duration_text
            )


    # ----------------------------------------------------
    # FALLBACK 2: STRAIGHT LINE, LAST RESORT.
    # Guarantees a line is always shown between source
    # and destination even if every routing service
    # failed.
    # ----------------------------------------------------

    if not coordinates:

        straight_line = [
            [source_lat, source_lon],
            [destination_lat, destination_lon]
        ]

        return (
            straight_line,
            "OK_FALLBACK_STRAIGHT_LINE",
            None
        )


    return coordinates, status, duration_text


# ============================================================
# GOOGLE PLACES TEXT SEARCH
# ============================================================
#
# Used to find real, named places (hotels, beaches,
# historical places, best areas for an activity, etc.)
# so they can be marked as pins on the map, instead of
# just being mentioned as text by the AI.
#
# Returns a list of NORMALIZED place dicts:
# {"name", "address", "rating", "lat", "lon", "maps_url"}
# so both this and the free fallback below can be drawn
# on the map the same way.
# ============================================================

def search_places_text(
    query,
    lat,
    lon,
    radius=40000,
    max_results=8
):

    url = (
        "https://places.googleapis.com/v1/"
        "places:searchText"
    )

    headers = {

        "Content-Type":
            "application/json",

        "X-Goog-Api-Key":
            GOOGLE_API_KEY,

        "X-Goog-FieldMask":
            (
                "places.displayName,"
                "places.formattedAddress,"
                "places.location,"
                "places.rating,"
                "places.googleMapsUri"
            )
    }

    body = {

        "textQuery":
            query,

        "maxResultCount":
            max_results,

        "locationBias": {

            "circle": {

                "center": {

                    "latitude":
                        lat,

                    "longitude":
                        lon

                },

                "radius":
                    float(radius)
            }
        }
    }

    try:

        response = requests.post(
            url,
            headers=headers,
            json=body,
            timeout=20
        )

        data = response.json()

        if "error" in data:

            error_message = data["error"].get(
                "message",
                "Unknown Places API error"
            )

            return [], error_message

        raw_places = data.get("places", [])

        if not raw_places:

            return [], "ZERO_RESULTS"

        normalized_places = []

        for place in raw_places:

            location = place.get(
                "location",
                {}
            )

            place_lat = location.get("latitude")
            place_lon = location.get("longitude")

            if place_lat is None or place_lon is None:

                continue

            normalized_places.append({

                "name": (
                    place
                    .get("displayName", {})
                    .get("text", "Unnamed place")
                ),

                "address": place.get(
                    "formattedAddress",
                    "Address unavailable"
                ),

                "rating": place.get(
                    "rating",
                    "N/A"
                ),

                "lat": place_lat,

                "lon": place_lon,

                "maps_url": place.get(
                    "googleMapsUri"
                )

            })

        if not normalized_places:

            return [], "ZERO_RESULTS"

        return normalized_places, "OK"

    except Exception as e:

        return [], str(e)


# ============================================================
# FREE FALLBACK PLACE SEARCH (NO API KEY NEEDED)
# ============================================================
#
# If Google Places fails (key not enabled, no billing,
# quota, etc.) this uses the free public Nominatim
# (OpenStreetMap) search API so hotels/attractions can
# still be marked without requiring any API key at all.
# Nominatim has no rating field, so "rating" is always
# "N/A" for these results.
# ============================================================

def search_places_nominatim(
    query,
    lat,
    lon,
    radius_km=40,
    max_results=8
):

    url = "https://nominatim.openstreetmap.org/search"

    # Build a rough bounding box around the location so
    # results stay near the destination.

    degree_radius = radius_km / 111.0

    viewbox = (
        f"{lon - degree_radius},{lat + degree_radius},"
        f"{lon + degree_radius},{lat - degree_radius}"
    )

    params = {

        "q": query,

        "format": "jsonv2",

        "limit": max_results,

        "viewbox": viewbox,

        "bounded": 1,

        "addressdetails": 1

    }

    headers = {

        "User-Agent": "ai_travel_movie_planner"

    }

    try:

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=20
        )

        results = response.json()

        if not results:

            return [], "ZERO_RESULTS"

        normalized_places = []

        for result in results:

            try:

                place_lat = float(result.get("lat"))
                place_lon = float(result.get("lon"))

            except (TypeError, ValueError):

                continue

            display_name = result.get(
                "display_name",
                "Unnamed place"
            )

            short_name = display_name.split(",")[0]

            normalized_places.append({

                "name": short_name,

                "address": display_name,

                "rating": "N/A",

                "lat": place_lat,

                "lon": place_lon,

                "maps_url": (
                    "https://www.openstreetmap.org/"
                    f"?mlat={place_lat}&mlon={place_lon}"
                    "#map=17/"
                    f"{place_lat}/{place_lon}"
                )

            })

        if not normalized_places:

            return [], "ZERO_RESULTS"

        return normalized_places, "OK"

    except Exception as e:

        return [], str(e)


# ============================================================
# FIND PLACES (WITH AUTOMATIC FREE FALLBACK)
# ============================================================
#
# Tries Google Places first. If that fails to return any
# results (API not enabled, no billing, quota, etc.), it
# automatically retries with the free Nominatim search so
# something still gets marked on the map.
#
# Returns: (places, source, status)
#   source is "google" or "nominatim_fallback"
# ============================================================

def find_places(
    query,
    lat,
    lon,
    radius=40000,
    max_results=8
):

    google_places, google_status = search_places_text(
        query,
        lat,
        lon,
        radius=radius,
        max_results=max_results
    )

    if google_places:

        return google_places, "google", google_status

    fallback_radius_km = max(radius / 1000, 5)

    nominatim_places, nominatim_status = (
        search_places_nominatim(
            query,
            lat,
            lon,
            radius_km=fallback_radius_km,
            max_results=max_results
        )
    )

    if nominatim_places:

        return (
            nominatim_places,
            "nominatim_fallback",
            nominatim_status
        )

    return [], "none", google_status


# ============================================================
# ADD PLACES TO MAP
# ============================================================
#
# Drops a marker for every NORMALIZED place dict (from
# either search_places_text() or
# search_places_nominatim()) onto a folium map, with a
# popup showing name, address, rating and a maps link.
# ============================================================

def add_places_to_map(
    places,
    target_map,
    color,
    icon_name,
    label_prefix
):

    marker_points = []

    for place in places:

        name = place.get(
            "name",
            label_prefix
        )

        address = place.get(
            "address",
            "Address unavailable"
        )

        rating = place.get(
            "rating",
            "N/A"
        )

        latitude = place.get("lat")
        longitude = place.get("lon")

        maps_url = place.get("maps_url")

        if latitude is None or longitude is None:

            continue

        popup_html = (
            f"<b>{label_prefix}: {name}</b><br>"
            f"{address}<br>"
            f"⭐ Rating: {rating}"
        )

        if maps_url:

            popup_html += (
                f"<br><a href='{maps_url}' "
                "target='_blank'>Open in Maps</a>"
            )

        folium.Marker(
            [latitude, longitude],
            tooltip=f"{label_prefix}: {name}",
            popup=folium.Popup(
                popup_html,
                max_width=300
            ),
            icon=folium.Icon(
                color=color,
                icon=icon_name,
                prefix="fa"
            )
        ).add_to(target_map)

        marker_points.append(
            [latitude, longitude]
        )

    return marker_points


# ============================================================
# TRAVEL FORM
# ============================================================

with st.form("travel_form"):

    st.subheader("📍 Trip Details")

    # --------------------------------------------------------
    # STARTING LOCATION
    # --------------------------------------------------------

    source = st.text_input(
        "📍 Starting Location",
        placeholder="Example: Kolkata"
    )

    # --------------------------------------------------------
    # DESTINATION
    # --------------------------------------------------------

    destination = st.text_input(
        "🎯 Destination",
        placeholder="Example: Goa"
    )

    # --------------------------------------------------------
    # DATE
    # --------------------------------------------------------

    travel_date = st.date_input(
        "📅 Travel Date",
        value=date.today()
    )

    # --------------------------------------------------------
    # TRAVELERS
    # --------------------------------------------------------

    traveler_option = st.selectbox(
        "👥 Number of Travelers",
        [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            "More than 10"
        ]
    )

    if traveler_option == "More than 10":

        travelers = st.number_input(
            "👥 Enter Exact Number of Travelers",
            min_value=11,
            max_value=1000,
            value=11,
            step=1
        )

    else:

        travelers = traveler_option


    # --------------------------------------------------------
    # NUMBER OF DAYS
    # --------------------------------------------------------

    number_of_days = st.number_input(
        "🗓️ Number of Days",
        min_value=1,
        max_value=30,
        value=5,
        step=1
    )


    # ========================================================
    # TRAVEL PREFERENCES
    # ========================================================

    st.subheader("⚙️ Travel Preferences")


    transport = st.selectbox(
        "🚆 What Kind of Transport to Prioritize",
        [
            "No Preference",
            "Flight",
            "Train",
            "Bus",
            "Car",
            "Walking",
            "Bicycle",
            "Cheapest Option",
            "Fastest Option"
        ]
    )


    hotel_type = st.selectbox(
        "🏨 What Type of Hotels",
        [
            "No Preference",
            "Budget Hotel",
            "3-Star Hotel",
            "4-Star Hotel",
            "5-Star Hotel",
            "Resort",
            "Boutique Hotel",
            "Hostel"
        ]
    )


    budget = st.selectbox(
        "💰 Budget Requirements",
        [
            "Budget",
            "Moderate",
            "Luxury",
            "No Budget Limit"
        ]
    )


    food_preference = st.selectbox(
        "🍴 Food Preferences",
        [
            "No Preference",
            "Vegetarian",
            "Non-Vegetarian",
            "Vegan",
            "Indian Food",
            "Local Cuisine",
            "Street Food",
            "Fine Dining"
        ]
    )


    places_to_visit = st.selectbox(
        "🗺️ Places You Want to Visit",
        [
            "No Preference",
            "Beaches",
            "Historical Places",
            "Nature & Wildlife",
            "Mountains",
            "Religious Places",
            "Museums",
            "Shopping Areas",
            "Popular Tourist Attractions",
            "Hidden Gems"
        ]
    )


    trip_purpose = st.selectbox(
        "🎯 Purpose of the Trip",
        [
            "Vacation",
            "Adventure",
            "Relaxation",
            "Honeymoon",
            "Family Trip",
            "Business",
            "Solo Travel",
            "Photography",
            "Cultural Experience"
        ]
    )


    travelling_with = st.selectbox(
        "🧑‍🤝‍🧑 Who You're Travelling With",
        [
            "Solo",
            "Family",
            "Friends",
            "Partner",
            "Children",
            "Colleagues"
        ]
    )


    activities = st.selectbox(
        "🏃 Activities You Prefer",
        [
            "No Preference",
            "Sightseeing",
            "Adventure Sports",
            "Water Sports",
            "Hiking",
            "Shopping",
            "Nightlife",
            "Photography",
            "Relaxing",
            "Cultural Activities",
            "Food Experiences"
        ]
    )


    # ========================================================
    # CUSTOM AI INSTRUCTION
    # ========================================================

    st.subheader("🤖 Customize Your AI Trip")

    custom_ai_instruction = st.text_area(
        "🤖 Completely Custom AI Instruction",
        placeholder=(
            "Example:\n"
            "I want a relaxed trip with less travelling between "
            "places. Include hidden local restaurants and avoid "
            "crowded tourist places."
        ),
        height=150
    )


    # ========================================================
    # MOVIE FINDER
    # ========================================================

    st.subheader("🎬 AI Movie Finder")

    st.write(
        "Tell the AI how you are feeling and it will recommend "
        "movies according to your mood."
    )


    movie_mood = st.text_area(
        "😊 What is your mood?",
        placeholder=(
            "Example: I am tired and stressed. "
            "I want something funny, relaxing and entertaining."
        ),
        height=100
    )


    movie_genre = st.selectbox(
        "🎭 Preferred Movie Genre",
        [
            "No Preference",
            "Action",
            "Adventure",
            "Comedy",
            "Romance",
            "Thriller",
            "Horror",
            "Drama",
            "Science Fiction",
            "Fantasy",
            "Animation",
            "Family",
            "Mystery",
            "Crime",
            "Documentary"
        ]
    )


    movie_language = st.selectbox(
        "🌐 Preferred Movie Language",
        [
            "No Preference",
            "English",
            "Hindi",
            "Bengali",
            "Tamil",
            "Telugu",
            "Malayalam",
            "Kannada",
            "Marathi",
            "Punjabi",
            "Any Language"
        ]
    )


    minimum_rating = st.selectbox(
        "⭐ Minimum IMDb/Rating Preference",
        [
            "No Preference",
            "6.0+",
            "6.5+",
            "7.0+",
            "7.5+",
            "8.0+"
        ]
    )


    movie_location = st.text_input(
        "📍 Movie Theater Location",
        placeholder=(
            "Example: Kolkata "
            "(leave empty to use your destination)"
        )
    )


    # ========================================================
    # SUBMIT
    # ========================================================

    submit = st.form_submit_button(
        "✈️ Plan My Trip & Find Movies"
    )


# ============================================================
# SAVE FORM DATA
# ============================================================

if submit:

    if not source.strip():

        st.warning(
            "⚠️ Please enter your starting location."
        )

    elif not destination.strip():

        st.warning(
            "⚠️ Please enter your destination."
        )

    elif not custom_ai_instruction.strip():

        st.warning(
            "⚠️ Please enter your custom AI instruction."
        )

    elif not movie_mood.strip():

        st.warning(
            "⚠️ Please enter your movie mood."
        )

    else:

        st.session_state.source = source

        st.session_state.destination = destination

        st.session_state.travel_date = travel_date

        st.session_state.travelers = travelers

        st.session_state.number_of_days = number_of_days

        st.session_state.transport = transport

        st.session_state.hotel_type = hotel_type

        st.session_state.budget = budget

        st.session_state.food_preference = food_preference

        st.session_state.places_to_visit = places_to_visit

        st.session_state.trip_purpose = trip_purpose

        st.session_state.travelling_with = travelling_with

        st.session_state.activities = activities

        st.session_state.custom_ai_instruction = (
            custom_ai_instruction
        )

        st.session_state.movie_mood = movie_mood

        st.session_state.movie_genre = movie_genre

        st.session_state.movie_language = movie_language

        st.session_state.minimum_rating = minimum_rating

        st.session_state.movie_location = (
            movie_location.strip()
            if movie_location.strip()
            else destination
        )

        st.session_state.show_result = True


# ============================================================
# RESULTS
# ============================================================

if st.session_state.show_result:

    source = st.session_state.source
    destination = st.session_state.destination

    travel_date = st.session_state.travel_date
    travelers = st.session_state.travelers

    number_of_days = st.session_state.number_of_days

    transport = st.session_state.transport
    hotel_type = st.session_state.hotel_type

    budget = st.session_state.budget

    food_preference = (
        st.session_state.food_preference
    )

    places_to_visit = (
        st.session_state.places_to_visit
    )

    trip_purpose = (
        st.session_state.trip_purpose
    )

    travelling_with = (
        st.session_state.travelling_with
    )

    activities = (
        st.session_state.activities
    )

    custom_ai_instruction = (
        st.session_state.custom_ai_instruction
    )

    movie_mood = (
        st.session_state.movie_mood
    )

    movie_genre = (
        st.session_state.movie_genre
    )

    movie_language = (
        st.session_state.movie_language
    )

    minimum_rating = (
        st.session_state.minimum_rating
    )

    movie_location = (
        st.session_state.movie_location
    )


    # ========================================================
    # LOCATION DETECTION
    # ========================================================

    st.divider()

    st.subheader("📍 Location Information")

    with st.spinner(
        "📍 Detecting your locations..."
    ):

        geolocator = Nominatim(
            user_agent="ai_travel_movie_planner"
        )

        try:

            current_location = (
                geolocator.geocode(source)
            )

            dest_location = (
                geolocator.geocode(destination)
            )

        except Exception as e:

            st.error(
                f"❌ Unable to detect locations: {e}"
            )

            st.stop()


    if not current_location:

        st.error(
            f"❌ Starting location '{source}' "
            "could not be found."
        )

        st.stop()


    if not dest_location:

        st.error(
            f"❌ Destination '{destination}' "
            "could not be found."
        )

        st.stop()


    # ========================================================
    # DISTANCE AND DURATION
    # ========================================================

    distance = "Not available"
    duration = "Not available"


    with st.spinner(
        "🛣️ Calculating distance and travel time..."
    ):

        try:

            distance_url = (
                "https://maps.googleapis.com/maps/api/"
                "distancematrix/json"
            )

            distance_params = {

                "origins":
                    f"{current_location.latitude},"
                    f"{current_location.longitude}",

                "destinations":
                    f"{dest_location.latitude},"
                    f"{dest_location.longitude}",

                "key":
                    GOOGLE_API_KEY

            }

            distance_response = requests.get(
                distance_url,
                params=distance_params,
                timeout=20
            )

            distance_data = (
                distance_response.json()
            )

            element = (
                distance_data[
                    "rows"
                ][0][
                    "elements"
                ][0]
            )

            if element.get("status") == "OK":

                distance = (
                    element[
                        "distance"
                    ]["text"]
                )

                duration = (
                    element[
                        "duration"
                    ]["text"]
                )

        except Exception as e:

            st.warning(
                f"⚠️ Distance calculation "
                f"unavailable: {e}"
            )


    # ========================================================
    # TRIP SUMMARY
    # ========================================================

    st.subheader("📊 Trip Summary")

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        st.metric(
            "📍 Distance",
            distance
        )

    with col2:

        st.metric(
            "⏱️ Travel Time",
            duration
        )

    with col3:

        st.metric(
            "👥 Travelers",
            travelers
        )

    with col4:

        st.metric(
            "🗓️ Trip Duration",
            f"{number_of_days} Days"
        )


    # ========================================================
    # USER PREFERENCES
    # ========================================================

    st.subheader(
        "📝 Your Trip Preferences"
    )

    col1, col2 = st.columns(2)

    with col1:

        st.info(
            f"""
**Starting Location:** {source}

**Destination:** {destination}

**Travel Date:** {travel_date}

**Travelers:** {travelers}

**Travelling With:** {travelling_with}

**Trip Purpose:** {trip_purpose}

**Budget:** {budget}
"""
        )

    with col2:

        st.info(
            f"""
**Transport:** {transport}

**Hotel:** {hotel_type}

**Food:** {food_preference}

**Places:** {places_to_visit}

**Activities:** {activities}

**Days:** {number_of_days}

**Custom AI Instruction:** {custom_ai_instruction}
"""
        )


    # ========================================================
    # REAL ROUTE MAP
    # ========================================================

    st.subheader("🗺️ Travel Route")


    mid_lat = (
        current_location.latitude +
        dest_location.latitude
    ) / 2

    mid_lon = (
        current_location.longitude +
        dest_location.longitude
    ) / 2


    route_map = folium.Map(
        location=[
            mid_lat,
            mid_lon
        ],
        zoom_start=5
    )


    # --------------------------------------------------------
    # START MARKER
    # --------------------------------------------------------

    folium.Marker(
        [
            current_location.latitude,
            current_location.longitude
        ],
        tooltip="Starting Location",
        popup=source,
        icon=folium.Icon(
            color="green"
        )
    ).add_to(route_map)


    # --------------------------------------------------------
    # DESTINATION MARKER
    # --------------------------------------------------------

    folium.Marker(
        [
            dest_location.latitude,
            dest_location.longitude
        ],
        tooltip="Destination",
        popup=destination,
        icon=folium.Icon(
            color="red"
        )
    ).add_to(route_map)


    # ========================================================
    # GET ACTUAL ROUTE
    # ========================================================

    route_coordinates = None
    route_status = None
    route_duration_text = None


    with st.spinner(
        f"🗺️ Calculating {transport.lower()} route..."
    ):

        route_coordinates, route_status, route_duration_text = (
            get_transport_route(

                current_location.latitude,

                current_location.longitude,

                dest_location.latitude,

                dest_location.longitude,

                transport

            )
        )


    # ========================================================
    # DRAW ROUTE
    # ========================================================

    if route_coordinates:

        if transport == "Car":

            route_name = (
                "🚗 Actual road route"
            )

        elif transport == "Bus":

            route_name = (
                "🚌 Transit/bus route"
            )

        elif transport == "Train":

            route_name = (
                "🚆 Transit/train route"
            )

        elif transport == "Walking":

            route_name = (
                "🚶 Walking route"
            )

        elif transport == "Bicycle":

            route_name = (
                "🚲 Bicycle route"
            )

        elif transport == "Flight":

            route_name = (
                "✈️ Flight path"
            )

        else:

            route_name = (
                "🛣️ Road route"
            )


        is_straight_line_fallback = (
            route_status == "OK_FALLBACK_STRAIGHT_LINE"
        )

        is_osrm_fallback = (
            route_status == "OK_FALLBACK_OSRM"
        )


        if is_straight_line_fallback:

            # Last-resort fallback: no routing service
            # could compute a path, so draw a dashed
            # straight line instead of hiding the route
            # entirely.

            folium.PolyLine(

                locations=route_coordinates,

                color="#d93025",

                weight=4,

                opacity=0.85,

                dash_array="10, 10",

                tooltip=(
                    route_name
                    + " (approximate straight line)"
                )

            ).add_to(route_map)

        else:

            folium.PolyLine(

                locations=route_coordinates,

                color="#a8c7fa",

                weight=11,

                opacity=0.9,

                tooltip=route_name

            ).add_to(route_map)

            folium.PolyLine(

                locations=route_coordinates,

                color="#1a73e8",

                weight=6,

                opacity=1.0,

                tooltip=route_name

            ).add_to(route_map)


        # ----------------------------------------------------
        # DURATION CHIP, LIKE THE "11 min" BUBBLE GOOGLE
        # MAPS SHOWS ALONG THE ROUTE.
        # ----------------------------------------------------

        if route_duration_text and not is_straight_line_fallback:

            midpoint_index = len(route_coordinates) // 2

            midpoint = route_coordinates[midpoint_index]

            chip_html = (
                "<div style='"
                "background:#1a73e8;"
                "color:white;"
                "padding:4px 12px;"
                "border-radius:14px;"
                "font-weight:bold;"
                "font-size:13px;"
                "white-space:nowrap;"
                "box-shadow:0 1px 4px rgba(0,0,0,0.5);"
                "border:2px solid white;"
                f"'>{route_duration_text}</div>"
            )

            folium.Marker(

                midpoint,

                icon=folium.DivIcon(
                    html=chip_html
                ),

                tooltip=(
                    f"{route_name} — "
                    f"{route_duration_text}"
                )

            ).add_to(route_map)


        if is_straight_line_fallback:

            st.warning(
                f"⚠️ {route_name}: no routing service "
                "could calculate an actual path "
                "(Google Directions failed and free "
                "OSRM routing also failed), so an "
                "**approximate straight-line path** "
                "is shown instead (dashed red)."
            )

        elif is_osrm_fallback:

            st.info(
                f"ℹ️ Google Directions could not be "
                "used, so this route was calculated "
                "using the free OSRM routing service "
                "instead. It still follows real "
                "roads, but travel time/cost estimates "
                "may be less precise than Google's."
            )

            st.success(
                f"✅ {route_name} displayed"
                + (
                    f" ({route_duration_text})"
                    if route_duration_text
                    else ""
                )
                + " via OSRM fallback."
            )

        else:

            st.success(
                f"✅ {route_name} displayed"
                + (
                    f" ({route_duration_text})"
                    if route_duration_text
                    else ""
                )
                + "."
            )


    else:

        st.warning(
            f"⚠️ Could not calculate the "
            f"{transport.lower()} route. "
            f"Reason: **{route_status}**. "
            "This usually means the Directions API "
            "is not enabled (or billing is not "
            "enabled) for your Google Maps API key, "
            "or the transit mode has no data for "
            "this route."
        )


    # ========================================================
    # HOTEL MARKERS ON THE MAP
    # ========================================================

    if hotel_type == "No Preference":

        hotel_query = f"hotels in {destination}"

    else:

        hotel_query = f"{hotel_type} in {destination}"

    with st.spinner(
        "🏨 Finding hotels to mark on the map..."
    ):

        hotel_places, hotel_source, hotel_status = (
            find_places(
                hotel_query,
                dest_location.latitude,
                dest_location.longitude
            )
        )

    if hotel_places:

        add_places_to_map(
            hotel_places,
            route_map,
            color="darkred",
            icon_name="bed",
            label_prefix="Hotel"
        )

        if hotel_source == "nominatim_fallback":

            st.caption(
                "🏨 Hotels marked using free "
                "OpenStreetMap search (Google "
                "Places was unavailable)."
            )

    else:

        st.caption(
            "🏨 No hotels could be marked on the "
            f"map. Reason: **{hotel_status}**."
        )


    # ========================================================
    # "PLACES YOU WANT TO VISIT" MARKERS ON THE MAP
    # ========================================================

    if places_to_visit == "No Preference":

        places_query = (
            f"popular tourist attractions near "
            f"{destination}"
        )

        places_label = "Attraction"

    else:

        places_query = (
            f"best {places_to_visit.lower()} "
            f"to visit near {destination}"
        )

        places_label = places_to_visit

    with st.spinner(
        f"🗺️ Marking {places_label.lower()} "
        f"near {destination}..."
    ):

        attraction_places, attraction_source, attraction_status = (
            find_places(
                places_query,
                dest_location.latitude,
                dest_location.longitude
            )
        )

    if attraction_places:

        add_places_to_map(
            attraction_places,
            route_map,
            color="purple",
            icon_name="star",
            label_prefix=places_label
        )

        if attraction_source == "nominatim_fallback":

            st.caption(
                f"🗺️ {places_label} marked using "
                "free OpenStreetMap search (Google "
                "Places was unavailable)."
            )

    else:

        st.caption(
            f"🗺️ No {places_label.lower()} "
            "could be marked on the map. "
            f"Reason: **{attraction_status}**."
        )


    # ========================================================
    # "BEST AREAS FOR YOUR ACTIVITY" MARKERS ON THE MAP
    # ========================================================

    if activities == "No Preference":

        activity_query = (
            f"best things to do near {destination}"
        )

        activity_label = "Best Area"

    else:

        activity_query = (
            f"best places for {activities.lower()} "
            f"near {destination}"
        )

        activity_label = activities

    with st.spinner(
        f"🏃 Marking the best areas for "
        f"{activity_label.lower()}..."
    ):

        activity_places, activity_source, activity_status = (
            find_places(
                activity_query,
                dest_location.latitude,
                dest_location.longitude
            )
        )

    if activity_places:

        add_places_to_map(
            activity_places,
            route_map,
            color="orange",
            icon_name="flag",
            label_prefix=activity_label
        )

        if activity_source == "nominatim_fallback":

            st.caption(
                f"🏃 {activity_label} areas marked "
                "using free OpenStreetMap search "
                "(Google Places was unavailable)."
            )

    else:

        st.caption(
            f"🏃 No best areas for "
            f"{activity_label.lower()} could be "
            f"marked on the map. "
            f"Reason: **{activity_status}**."
        )


    # ========================================================
    # MAP LEGEND
    # ========================================================

    legend_parts = [
        "🟢 Start",
        "🔴 Destination",
        "🔵 Route",
        "🟤 Hotels",
        f"🟣 {places_label}",
        f"🟠 {activity_label}"
    ]

    st.caption(
        "  ·  ".join(legend_parts)
    )


    # ========================================================
    # SHOW MAP
    # ========================================================

    st_folium(
        route_map,
        width=700,
        height=500
    )


    # ========================================================
    # AI TRIP INFORMATION
    # ========================================================

    user_trip_preferences = f"""
USER TRAVEL REQUEST
===================

Starting Location:
{source}

Destination:
{destination}

Travel Date:
{travel_date}

Number of Days:
{number_of_days}

Number of Travelers:
{travelers}

Travelling With:
{travelling_with}

Budget:
{budget}

Transport Preference:
{transport}

Hotel Preference:
{hotel_type}

Food Preference:
{food_preference}

Places to Visit:
{places_to_visit}

Trip Purpose:
{trip_purpose}

Preferred Activities:
{activities}

Completely Custom User Instruction:
{custom_ai_instruction}

Known Distance:
{distance}

Known Approximate Duration:
{duration}

IMPORTANT:

Use ALL user preferences.

Do not ignore the custom instruction.

Do not invent real-time availability.

Clearly identify approximate prices
and travel times.
"""


    # ========================================================
    # SINGLE COMBINED GEMINI CALL
    # ========================================================
    #
    # All four AI sections (travel options, hotels,
    # itinerary and movie recommendations) are generated
    # from ONE Gemini API call instead of four separate
    # calls, so the Gemini API key is only used once per
    # trip generated, not four times.
    # ========================================================

    combined_prompt = f"""
You are an expert AI travel planner AND an expert
movie recommendation AI, combined into a single
assistant for this task.

You must produce FOUR separate sections in a single
response. Each section MUST start and end with the
EXACT markers shown below, each on its own line, with
nothing else on that line. Do not add any commentary
before ###SECTION:TRAVEL_OPTIONS### or after
###END:MOVIES###.

###SECTION:TRAVEL_OPTIONS###

User request:

{user_trip_preferences}

Create the best travel options from
{source} to {destination}.

Preferred transport:
{transport}

Compare relevant transport options.

Include:

• Recommended transport
• Alternative transport
• Approximate travel time
• Approximate cost
• Advantages
• Disadvantages
• Best option

Consider:

• Budget
• Number of travelers
• Travelling companions
• Trip purpose
• Travel date
• Number of days
• Food
• Activities
• Places to visit
• Custom instruction

Do not claim real-time prices
or availability.

###END:TRAVEL_OPTIONS###

###SECTION:HOTELS###

User requirements:

{user_trip_preferences}

Recommend around 5 suitable hotels
in {destination}.

Hotel preference:
{hotel_type}

Budget:
{budget}

Travelers:
{travelers}

Travelling with:
{travelling_with}

For each hotel include:

• Hotel name
• Hotel type
• Approximate price range
• Location/area
• Why it may suit the user
• Suitability for the group

Do not claim real-time availability.
Prices must be described as approximate.

###END:HOTELS###

###SECTION:ITINERARY###

Create a personalized
{number_of_days}-day itinerary
for {destination}.

User requirements:

{user_trip_preferences}

The itinerary must respect:

• Number of days
• Travel date
• Travelers
• Travelling with
• Budget
• Transport
• Hotel
• Food
• Places
• Trip purpose
• Activities
• Custom instruction

For every day:

DAY X

Morning:
Afternoon:
Evening:

Include:

• Places to visit
• Activities
• Food suggestions
• Relaxation time
• Practical travel suggestions

Do not overload each day.

Consider travel time between attractions.

Do not claim real-time availability.

###END:ITINERARY###

###SECTION:MOVIES###

You are also acting as a movie recommendation AI here.

The user's mood is:

{movie_mood}

Preferred genre:
{movie_genre}

Preferred language:
{movie_language}

Minimum rating:
{minimum_rating}

Location:
{movie_location}

Travelling with:
{travelling_with}

Number of people:
{travelers}

Recommend 5 movies that strongly match
the user's mood and preferences.

For every movie provide:

1. Movie title
2. Language
3. Genre
4. Approximate rating
5. Short description
6. Why it matches the mood
7. Mood match score from 1-100

Do not invent current showtimes.

Do not claim that a movie is currently
playing in a theater.

Focus on movie recommendations.

###END:MOVIES###

Remember: use ALL user preferences, do not ignore the
custom instruction, and never invent real-time
availability, prices or showtimes anywhere in your
response.
"""


    def extract_section(full_text, section_name):

        start_marker = f"###SECTION:{section_name}###"
        end_marker = f"###END:{section_name}###"

        start_index = full_text.find(start_marker)
        end_index = full_text.find(end_marker)

        if start_index == -1 or end_index == -1:

            return None

        start_index += len(start_marker)

        return full_text[start_index:end_index].strip()


    ai_error = None

    travel_options_text = None
    hotel_text = None
    itinerary_text = None
    movie_text = None

    with st.spinner(
        "🤖 AI is planning your entire trip "
        "(travel options, hotels, itinerary and "
        "movies) in a single request..."
    ):

        try:

            combined_response = model.generate_content(
                combined_prompt
            )

            full_ai_text = combined_response.text

            travel_options_text = extract_section(
                full_ai_text,
                "TRAVEL_OPTIONS"
            )

            hotel_text = extract_section(
                full_ai_text,
                "HOTELS"
            )

            itinerary_text = extract_section(
                full_ai_text,
                "ITINERARY"
            )

            movie_text = extract_section(
                full_ai_text,
                "MOVIES"
            )

            # ------------------------------------------------
            # If the model did not follow the section markers
            # exactly, fall back to showing the full raw
            # response in every tab instead of calling the
            # API again just to retry the format.
            # ------------------------------------------------

            if not any(
                [
                    travel_options_text,
                    hotel_text,
                    itinerary_text,
                    movie_text
                ]
            ):

                travel_options_text = full_ai_text
                hotel_text = full_ai_text
                itinerary_text = full_ai_text
                movie_text = full_ai_text

        except Exception as e:

            ai_error = str(e)


    # ========================================================
    # TABS
    # ========================================================

    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "🚆 Travel Options",
            "🏨 Hotels",
            "🗓️ Itinerary",
            "🎬 AI Movie Finder"
        ]
    )


    # ========================================================
    # TRAVEL OPTIONS
    # ========================================================

    with tab1:

        st.subheader(
            "🚆 AI Travel Options"
        )

        if ai_error:

            st.error(
                f"❌ Travel recommendation "
                f"failed: {ai_error}"
            )

        elif travel_options_text:

            st.write(
                travel_options_text
            )

        else:

            st.warning(
                "⚠️ The travel options section "
                "was not returned by the AI."
            )


    # ========================================================
    # HOTELS
    # ========================================================

    with tab2:

        st.subheader(
            "🏨 AI Hotel Recommendations"
        )

        if ai_error:

            st.error(
                f"❌ Hotel recommendation "
                f"failed: {ai_error}"
            )

        elif hotel_text:

            st.write(
                hotel_text
            )

        else:

            st.warning(
                "⚠️ The hotel recommendations "
                "section was not returned by the AI."
            )


    # ========================================================
    # ITINERARY
    # ========================================================

    with tab3:

        st.subheader(
            f"🗓️ {number_of_days}-Day Itinerary"
        )

        if ai_error:

            st.error(
                f"❌ Itinerary generation "
                f"failed: {ai_error}"
            )

        elif itinerary_text:

            st.write(
                itinerary_text
            )

        else:

            st.warning(
                "⚠️ The itinerary section was "
                "not returned by the AI."
            )


    # ========================================================
    # MOVIE FINDER
    # ========================================================

    with tab4:

        st.subheader(
            "🎬 AI Movie Finder"
        )

        st.write(
            f"📍 Theater search location: "
            f"**{movie_location}**"
        )

        st.write(
            f"😊 Your mood: **{movie_mood}**"
        )


        # ====================================================
        # MOVIE RECOMMENDATIONS
        # ====================================================

        st.caption(
            "🎬 Movie recommendations below come "
            "from the same single AI request used "
            "for the rest of your trip plan."
        )

        if ai_error:

            st.error(
                f"❌ Movie recommendation "
                f"failed: {ai_error}"
            )

        elif movie_text:

            st.write(
                movie_text
            )

        else:

            st.warning(
                "⚠️ The movie recommendations "
                "section was not returned by the AI."
            )


        # ====================================================
        # THEATER SEARCH
        # ====================================================

        st.divider()

        st.subheader(
            "🏢 Movie Theaters Near You"
        )

        st.info(
            "Google Places is used to find real "
            "movie theater locations. Current "
            "movie showtimes require a dedicated "
            "cinema/showtime data source."
        )


        # ====================================================
        # GEOCODE MOVIE LOCATION
        # ====================================================

        movie_geolocator = Nominatim(
            user_agent="ai_movie_finder"
        )

        with st.spinner(
            "📍 Finding theater location..."
        ):

            try:

                movie_geo = (
                    movie_geolocator.geocode(
                        movie_location
                    )
                )

            except Exception:

                movie_geo = None


        if movie_geo:

            # =================================================
            # GOOGLE PLACES API
            # =================================================

            places_url = (
                "https://places.googleapis.com/v1/"
                "places:searchNearby"
            )

            places_headers = {

                "Content-Type":
                    "application/json",

                "X-Goog-Api-Key":
                    GOOGLE_API_KEY,

                "X-Goog-FieldMask":
                    (
                        "places.displayName,"
                        "places.formattedAddress,"
                        "places.location,"
                        "places.rating,"
                        "places.googleMapsUri"
                    )
            }


            places_body = {

                "includedTypes":
                    ["movie_theater"],

                "maxResultCount":
                    10,

                "rankPreference":
                    "DISTANCE",

                "locationRestriction": {

                    "circle": {

                        "center": {

                            "latitude":
                                movie_geo.latitude,

                            "longitude":
                                movie_geo.longitude

                        },

                        "radius":
                            30000.0
                    }
                }
            }


            try:

                places_response = requests.post(

                    places_url,

                    headers=places_headers,

                    json=places_body,

                    timeout=20

                )

                places_data = (
                    places_response.json()
                )

                theaters = (
                    places_data.get(
                        "places",
                        []
                    )
                )

            except Exception as e:

                theaters = []

                st.error(
                    f"❌ Theater search failed: {e}"
                )


            # =================================================
            # DISPLAY THEATERS
            # =================================================

            if theaters:

                st.success(
                    f"🎬 Found {len(theaters)} "
                    "nearby movie theaters."
                )


                theater_map = folium.Map(

                    location=[
                        movie_geo.latitude,
                        movie_geo.longitude
                    ],

                    zoom_start=12

                )


                folium.Marker(

                    [
                        movie_geo.latitude,
                        movie_geo.longitude
                    ],

                    tooltip="Movie Search Location",

                    popup=movie_location,

                    icon=folium.Icon(
                        color="blue"
                    )

                ).add_to(theater_map)


                for theater in theaters:

                    display_name = (
                        theater
                        .get(
                            "displayName",
                            {}
                        )
                        .get(
                            "text",
                            "Movie Theater"
                        )
                    )

                    address = theater.get(
                        "formattedAddress",
                        "Address unavailable"
                    )

                    rating = theater.get(
                        "rating",
                        "N/A"
                    )

                    location = theater.get(
                        "location",
                        {}
                    )

                    latitude = location.get(
                        "latitude"
                    )

                    longitude = location.get(
                        "longitude"
                    )

                    maps_url = theater.get(
                        "googleMapsUri"
                    )


                    if (
                        latitude is not None
                        and
                        longitude is not None
                    ):

                        popup_text = (
                            f"{display_name}<br>"
                            f"{address}<br>"
                            f"⭐ Rating: {rating}"
                        )

                        folium.Marker(

                            [
                                latitude,
                                longitude
                            ],

                            tooltip=display_name,

                            popup=popup_text,

                            icon=folium.Icon(
                                color="red",
                                icon="film"
                            )

                        ).add_to(
                            theater_map
                        )


                    with st.container():

                        st.write(
                            f"### 🎬 {display_name}"
                        )

                        st.write(
                            f"📍 {address}"
                        )

                        st.write(
                            f"⭐ Rating: {rating}"
                        )

                        if maps_url:

                            st.write(
                                f"🗺️ [Open "
                                f"{display_name} "
                                f"on Google Maps]"
                                f"({maps_url})"
                            )

                        st.caption(
                            "⚠️ This confirms the theater "
                            "location, not the current "
                            "movie showtime."
                        )

                        st.divider()


                # =============================================
                # THEATER MAP
                # =============================================

                st.subheader(
                    "🗺️ Nearby Movie Theater Map"
                )

                st_folium(
                    theater_map,
                    width=700,
                    height=500
                )

            else:

                st.warning(
                    "⚠️ No nearby movie theaters "
                    "were found."
                )

        else:

            st.error(
                f"❌ Could not find movie location: "
                f"{movie_location}"
            )


        # ====================================================
        # MOVIE TRANSPARENCY
        # ====================================================

        st.divider()

        st.subheader(
            "🔍 Movie Recommendation Transparency"
        )

        st.write(
            "😊 **Mood Analysis:** Gemini analyzes "
            "the mood entered by the user."
        )

        st.write(
            "🎬 **Movie Recommendation:** Gemini "
            "matches movies with mood, genre, "
            "language and rating."
        )

        st.write(
            "🏢 **Theater Discovery:** Google Places "
            "finds real theater locations."
        )

        st.write(
            "🗺️ **Theater Map:** Nearby theaters "
            "are displayed on an interactive map."
        )

        st.warning(
            "⚠️ Live movie showtimes and movie-specific "
            "availability are not claimed because the "
            "Google Places API does not provide a universal "
            "live cinema-showtime feed."
        )


    # ========================================================
    # OVERALL TRANSPARENCY
    # ========================================================

    st.divider()

    st.subheader(
        "🔍 Overall AI Planning Transparency"
    )

    st.write(
        "📍 **Location Detection:** "
        "Geocoding converts locations into coordinates."
    )

    st.write(
        "🛣️ **Distance Calculation:** "
        "Google Maps calculates distance and duration."
    )

    st.write(
        "🗺️ **Route Mapping:** "
        "The application requests route geometry "
        "instead of drawing a straight line."
    )

    st.write(
        "🚗 **Road Transport:** "
        "Car routes follow the road network returned "
        "by Google Directions."
    )

    st.write(
        "🚆 **Train/Bus:** "
        "Google Transit is used where transit data "
        "is available."
    )

    st.write(
        "✈️ **Flight:** "
        "A great-circle flight path is displayed."
    )

    st.write(
        "🤖 **AI Planning:** "
        "Gemini uses the user's preferences to "
        "generate travel recommendations."
    )

    st.write(
        "🏨 **Hotels:** "
        "Gemini generates hotel recommendations."
    )

    st.write(
        f"🗓️ **Itinerary:** "
        f"Gemini generates the personalized "
        f"{number_of_days}-day itinerary."
    )

    st.write(
        "🎬 **Movies:** "
        "Gemini recommends movies according "
        "to the user's mood."
    )

    st.write(
        "🏢 **Theaters:** "
        "Google Places finds nearby movie theaters."
    )


    st.warning(
        "⚠️ Always verify travel prices, hotel prices, "
        "movie availability, showtimes and booking "
        "information before making a purchase."
    )


    # ========================================================
    # NEW TRIP
    # ========================================================

    st.divider()

    if st.button(
        "🔄 Start New Trip"
    ):

        st.session_state.show_result = False

        st.rerun()
