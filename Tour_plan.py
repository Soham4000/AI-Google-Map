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

model = genai.GenerativeModel("gemini-3.7-flash")


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

            return None, data.get(
                "status",
                "UNKNOWN_ERROR"
            )

        routes = data.get("routes", [])

        if not routes:

            return None, "NO_ROUTE"

        route = routes[0]

        overview = route.get(
            "overview_polyline",
            {}
        )

        encoded = overview.get("points")

        if not encoded:

            return None, "NO_POLYLINE"

        coordinates = decode_polyline(encoded)

        return coordinates, "OK"

    except Exception as e:

        return None, str(e)


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
# ROUTE BASED ON TRANSPORT
# ============================================================

def get_transport_route(
    source_lat,
    source_lon,
    destination_lat,
    destination_lon,
    transport
):

    # --------------------------------------------------------
    # CAR
    # --------------------------------------------------------

    if transport == "Car":

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="driving"
        )


    # --------------------------------------------------------
    # BUS
    # --------------------------------------------------------

    elif transport == "Bus":

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="transit",
            transit_mode="bus"
        )


    # --------------------------------------------------------
    # TRAIN
    # --------------------------------------------------------

    elif transport == "Train":

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="transit",
            transit_mode="train"
        )


    # --------------------------------------------------------
    # WALKING
    # --------------------------------------------------------

    elif transport == "Walking":

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="walking"
        )


    # --------------------------------------------------------
    # BICYCLE
    # --------------------------------------------------------

    elif transport == "Bicycle":

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="bicycling"
        )


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

        return coordinates, "OK"


    # --------------------------------------------------------
    # DEFAULT
    # --------------------------------------------------------

    else:

        return get_google_route(
            source_lat,
            source_lon,
            destination_lat,
            destination_lon,
            mode="driving"
        )


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


    with st.spinner(
        f"🗺️ Calculating {transport.lower()} route..."
    ):

        route_coordinates, route_status = (
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


        folium.PolyLine(

            locations=route_coordinates,

            color="blue",

            weight=6,

            opacity=0.9,

            tooltip=route_name

        ).add_to(route_map)


        st.success(
            f"✅ {route_name} displayed."
        )


    else:

        st.warning(
            f"⚠️ Could not calculate the "
            f"{transport.lower()} route."
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

        travel_prompt = f"""
You are an expert AI travel planner.

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
"""

        with st.spinner(
            "🤖 AI is analyzing travel options..."
        ):

            try:

                response = model.generate_content(
                    travel_prompt
                )

                st.write(
                    response.text
                )

            except Exception as e:

                st.error(
                    f"❌ Travel recommendation "
                    f"failed: {e}"
                )


    # ========================================================
    # HOTELS
    # ========================================================

    with tab2:

        st.subheader(
            "🏨 AI Hotel Recommendations"
        )

        hotel_prompt = f"""
You are an expert AI travel planner.

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
"""

        with st.spinner(
            "🏨 AI is finding suitable hotels..."
        ):

            try:

                response = model.generate_content(
                    hotel_prompt
                )

                st.write(
                    response.text
                )

            except Exception as e:

                st.error(
                    f"❌ Hotel recommendation "
                    f"failed: {e}"
                )


    # ========================================================
    # ITINERARY
    # ========================================================

    with tab3:

        st.subheader(
            f"🗓️ {number_of_days}-Day Itinerary"
        )

        itinerary_prompt = f"""
You are an expert AI travel planner.

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
"""

        with st.spinner(
            "🗓️ AI is creating your itinerary..."
        ):

            try:

                response = model.generate_content(
                    itinerary_prompt
                )

                st.write(
                    response.text
                )

            except Exception as e:

                st.error(
                    f"❌ Itinerary generation "
                    f"failed: {e}"
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

        movie_prompt = f"""
You are an expert movie recommendation AI.

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

IMPORTANT:

Do not invent current showtimes.

Do not claim that a movie is currently
playing in a theater.

Focus on movie recommendations.
"""

        with st.spinner(
            "🤖 AI is understanding your mood..."
        ):

            try:

                response = model.generate_content(
                    movie_prompt
                )

                st.write(
                    response.text
                )

            except Exception as e:

                st.error(
                    f"❌ Movie recommendation "
                    f"failed: {e}"
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
