
import re
import requests
import streamlit as st

# =========================================================
# 1. CONFIGURATION
# =========================================================

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5-coder:7b"

GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
CURRENCY_URL = "https://api.frankfurter.dev/v2/rate"
TIME_URL = "https://timeapi.io/api/Time/current/zone"

REQUEST_TIMEOUT = 25

st.set_page_config(
    page_title="Multi-Tool AI Agent",
    page_icon="🤖",
)

st.title("🤖 Multi-Tool AI Agent")
st.caption(
    "Ask about weather, world time, and currency conversion. "
    "Follow-up questions are supported."
)

# =========================================================
# 2. CURRENCY ALIASES
# =========================================================

CURRENCY_ALIASES = {
    "EURO": "EUR",
    "EUROS": "EUR",
    "EUR": "EUR",
    "HUF": "HUF",
    "FORINT": "HUF",
    "FORINTS": "HUF",
    "USD": "USD",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "US DOLLARS": "USD",
    "GBP": "GBP",
    "POUND": "GBP",
    "POUNDS": "GBP",
    "JPY": "JPY",
    "YEN": "JPY",
    "GHS": "GHS",
    "CEDI": "GHS",
    "CEDIS": "GHS",
    "CAD": "CAD",
    "AUD": "AUD",
    "CHF": "CHF",
    "INR": "INR",
    "CNY": "CNY",
    "PLN": "PLN",
    "CZK": "CZK",
}

CURRENCY_PATTERN = (
    r"EUR|EUROS?|HUF|FORINTS?|USD|US DOLLARS?|DOLLARS?|"
    r"GBP|POUNDS?|JPY|YEN|GHS|CEDIS?|CAD|AUD|CHF|INR|CNY|PLN|CZK"
)


def normalize_currency(value):
    value = re.sub(r"\s+", " ", value.upper().strip())
    return CURRENCY_ALIASES.get(value, value)


# =========================================================
# 3. EXTERNAL API HELPERS
# =========================================================

def get_json(url, params=None):
    response = requests.get(
        url,
        params=params,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return response.json()


def find_city(city_name, cache):
    city_name = city_name.strip(" .,?!")
    if not city_name:
        raise ValueError("Please provide a city name.")

    key = city_name.lower()

    if key in cache:
        return cache[key]

    data = get_json(
        GEOCODING_URL,
        params={
            "name": city_name,
            "count": 5,
            "language": "en",
            "format": "json",
        },
    )

    places = data.get("results", [])

    if not places:
        raise ValueError(
            f"I couldn't find a city named '{city_name}'. "
            "Please check the spelling or include the country."
        )

    # Use the first matching result for this learning version.
    place = places[0]
    cache[key] = place
    return place


def city_label(place):
    parts = [place.get("name", "Unknown city")]

    if place.get("admin1"):
        parts.append(place["admin1"])

    if place.get("country"):
        parts.append(place["country"])

    return ", ".join(parts)


# =========================================================
# 4. WEATHER TOOL
# =========================================================

WEATHER_CODES = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    71: "Slight snow",
    73: "Moderate snow",
    75: "Heavy snow",
    80: "Rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    95: "Thunderstorm",
    96: "Thunderstorm with hail",
    99: "Thunderstorm with heavy hail",
}


def weather_tool(location, city_cache):
    place = find_city(location, city_cache)

    data = get_json(
        WEATHER_URL,
        params={
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "current": (
                "temperature_2m,"
                "relative_humidity_2m,"
                "apparent_temperature,"
                "precipitation,"
                "wind_speed_10m,"
                "weather_code"
            ),
            "timezone": "auto",
        },
    )

    current = data.get("current", {})

    if not current:
        raise ValueError("The weather service returned no current conditions.")

    return {
        "service": "weather",
        "location": city_label(place),
        "timezone": data.get("timezone"),
        "observation_time": current.get("time"),
        "temperature": current.get("temperature_2m"),
        "humidity": current.get("relative_humidity_2m"),
        "feels_like": current.get("apparent_temperature"),
        "precipitation": current.get("precipitation"),
        "wind_speed": current.get("wind_speed_10m"),
        "weather": WEATHER_CODES.get(
            current.get("weather_code"),
            f"Weather code {current.get('weather_code')}",
        ),
        "units": data.get("current_units", {}),
    }


# =========================================================
# 5. WORLD TIME TOOL
# =========================================================

def time_tool(location, city_cache):
    place = find_city(location, city_cache)
    timezone_name = place.get("timezone")

    if not timezone_name:
        raise ValueError("I couldn't find the city's time zone.")

    data = get_json(
        TIME_URL,
        params={"timeZone": timezone_name},
    )

    return {
        "service": "time",
        "location": city_label(place),
        "timezone": timezone_name,
        "date_time": data.get("dateTime", data.get("datetime")),
        "day_of_week": data.get("dayOfWeek"),
    }


# =========================================================
# 6. CURRENCY TOOL
# =========================================================

def currency_tool(amount, source, target):
    amount = float(amount)
    source = normalize_currency(source)
    target = normalize_currency(target)

    if amount <= 0:
        raise ValueError("The amount must be greater than zero.")

    if not re.fullmatch(r"[A-Z]{3}", source):
        raise ValueError("The source currency is invalid.")

    if not re.fullmatch(r"[A-Z]{3}", target):
        raise ValueError("The target currency is invalid.")

    if source == target:
        return {
            "service": "currency",
            "amount": amount,
            "from_currency": source,
            "to_currency": target,
            "rate": 1.0,
            "converted_amount": amount,
            "rate_date": None,
        }

    data = get_json(f"{CURRENCY_URL}/{source}/{target}")

    rate = float(data["rate"])

    return {
        "service": "currency",
        "amount": amount,
        "from_currency": source,
        "to_currency": target,
        "rate": rate,
        "converted_amount": amount * rate,
        "rate_date": data.get("date"),
        "note": (
            "This is an indicative reference rate. "
            "Your bank or transfer provider may offer a different rate "
            "or charge fees."
        ),
    }


# =========================================================
# 7. REQUEST RECOGNITION
# =========================================================

def extract_currency_request(question):
    text = question.upper().replace(",", "")

    # Example: convert 600 EUR to HUF
    patterns = [
        rf"(?:CONVERT\s+)?(\d+(?:\.\d+)?)\s+({CURRENCY_PATTERN})"
        rf"\s+(?:TO|INTO|IN)\s+({CURRENCY_PATTERN})",

        # Example: how much is 600 euros in Hungarian forints?
        rf"HOW MUCH (?:IS|ARE)\s+(\d+(?:\.\d+)?)\s+"
        rf"({CURRENCY_PATTERN})\s+(?:WORTH\s+)?(?:IN|TO)\s+"
        rf"({CURRENCY_PATTERN})",

        # Example: convert 600 euros into forints
        rf"CONVERT\s+(\d+(?:\.\d+)?)\s+({CURRENCY_PATTERN})"
        rf"\s+INTO\s+({CURRENCY_PATTERN})",
    ]

    for pattern in patterns:
        match = re.search(pattern, text)

        if match:
            amount, source, target = match.groups()
            return {
                "amount": float(amount),
                "from_currency": normalize_currency(source),
                "to_currency": normalize_currency(target),
            }

    return None


def extract_location(question):
    # Prefer the location following common prepositions.
    patterns = [
        r"\b(?:weather|temperature|time)\s+in\s+(.+?)[?.!,]*$",
        r"\b(?:in|at)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*?)[?.!,]*$",
        r"\bfor\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*?)[?.!,]*$",
    ]

    for pattern in patterns:
        match = re.search(pattern, question.strip(), re.IGNORECASE)

        if match:
            location = match.group(1).strip(" .,?!")

            # Remove trailing conversational words.
            location = re.sub(
                r"\s+(AND WHAT TIME IS IT THERE|AND WHAT TIME IS IT|"
                r"AND THE TIME|RIGHT NOW)$",
                "",
                location,
                flags=re.IGNORECASE,
            ).strip()

            if location:
                return location

    return None


def latest_user_question(messages):
    for message in reversed(messages):
        if message.get("role") == "user":
            return message.get("content", "")
    return ""


def has_weather_intent(question):
    text = question.lower()
    return any(term in text for term in [
        "weather",
        "temperature",
        "rain",
        "raining",
        "snow",
        "sunny",
        "cloudy",
        "wind",
        "wear winter clothes",
        "wear warm clothes",
        "what should i wear",
        "do i need a jacket",
        "do i need a coat",
        "is it cold",
        "is it hot",
    ])


def has_time_intent(question):
    text = question.lower()
    return any(term in text for term in [
        "what time",
        "current time",
        "local time",
        "time in",
        "time there",
        "date and time",
    ])


def resolve_followup(question, prior_messages):
    """
    Resolve simple location follow-ups without asking the AI
    to rewrite the question.
    """
    text = question.strip()
    lower = text.lower()

    followup_match = re.fullmatch(
        r"(?:what about|how about|and|what's it like in|"
        r"what is it like in)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]*)[?.!]*",
        text,
        flags=re.IGNORECASE,
    )

    if not followup_match:
        return text

    new_location = followup_match.group(1).strip(" .,?!")

    previous_question = latest_user_question(prior_messages)

    if not previous_question:
        return text

    # A follow-up can carry over the previous currency pair.
    previous_currency = extract_currency_request(previous_question)

    if previous_currency:
        amount_match = re.search(
            r"\b(\d+(?:\.\d+)?)\b",
            text,
        )

        if amount_match:
            return (
                f"Convert {amount_match.group(1)} "
                f"{previous_currency['from_currency']} to "
                f"{previous_currency['to_currency']}"
            )

    previous_location = extract_location(previous_question)

    if not previous_location:
        return text

    requests_weather = has_weather_intent(previous_question)
    requests_time = has_time_intent(previous_question)

    if requests_weather and requests_time:
        return (
            f"What's the weather in {new_location}, "
            f"and what time is it in {new_location}?"
        )

    if requests_weather:
        return f"What's the weather in {new_location}?"

    if requests_time:
        return f"What time is it in {new_location}?"

    return text


# =========================================================
# 8. ROUTE REQUESTS WITHOUT AN AI PLANNER
# =========================================================

def route_question(question, prior_messages):
    resolved = resolve_followup(question, prior_messages)
    currency_request = extract_currency_request(resolved)

    if currency_request:
        return resolved, [{
            "tool": "currency",
            **currency_request,
        }], None

    calls = []
    location = extract_location(resolved)

    if has_weather_intent(resolved):
        if not location:
            return resolved, [], (
                "Which city would you like the weather for?"
            )

        calls.append({
            "tool": "weather",
            "location": location,
        })

    if has_time_intent(resolved):
        if not location:
            return resolved, [], (
                "Which city's local time would you like to know?"
            )

        calls.append({
            "tool": "time",
            "location": location,
        })

    if calls:
        return resolved, calls, None

    return resolved, [], (
        "I can currently help with weather, local time, and currency "
        "conversion. For example, ask 'What's the weather in Tokyo?', "
        "'What time is it in Budapest?', or 'Convert 600 EUR to HUF'."
    )


# =========================================================
# 9. EXECUTE TOOL CALLS
# =========================================================

def execute_tools(calls):
    results = []
    city_cache = {}

    for call in calls:
        tool = call["tool"]

        try:
            if tool == "weather":
                result = weather_tool(
                    call["location"],
                    city_cache,
                )

            elif tool == "time":
                result = time_tool(
                    call["location"],
                    city_cache,
                )

            elif tool == "currency":
                result = currency_tool(
                    call["amount"],
                    call["from_currency"],
                    call["to_currency"],
                )

            else:
                raise ValueError(f"Unsupported tool: {tool}")

            results.append({
                "tool": tool,
                "status": "success",
                "result": result,
            })

        except requests.exceptions.HTTPError as error:
            results.append({
                "tool": tool,
                "status": "error",
                "error": f"The external service returned an HTTP error: {error}",
            })

        except requests.exceptions.RequestException as error:
            results.append({
                "tool": tool,
                "status": "error",
                "error": f"Network error while contacting the service: {error}",
            })

        except (ValueError, KeyError, TypeError) as error:
            results.append({
                "tool": tool,
                "status": "error",
                "error": str(error),
            })

    return results


# =========================================================
# 10. BUILD ANSWERS FROM REAL RESULTS
# =========================================================

def format_number(value, decimals=2):
    if value is None:
        return "Unavailable"

    return f"{value:,.{decimals}f}"


def answer_from_results(question, results):
    answers = []
    lower = question.lower()

    for item in results:
        if item["status"] == "error":
            answers.append(
                f"**{item['tool'].title()} service error:** "
                f"{item['error']}"
            )
            continue

        data = item["result"]
        tool = item["tool"]

        if tool == "weather":
            answers.append(
                f"### Current weather in {data['location']}\n"
                f"- **Conditions:** {data['weather']}\n"
                f"- **Temperature:** "
                f"{format_number(data['temperature'], 1)}°C\n"
                f"- **Feels like:** "
                f"{format_number(data['feels_like'], 1)}°C\n"
                f"- **Humidity:** "
                f"{format_number(data['humidity'], 0)}%\n"
                f"- **Precipitation:** "
                f"{format_number(data['precipitation'], 1)} mm\n"
                f"- **Wind speed:** "
                f"{format_number(data['wind_speed'], 1)} km/h\n"
                f"- **Local observation time:** "
                f"{data['observation_time']}\n"
                f"- **Time zone:** {data['timezone']}\n\n"
                f"*These are current conditions, not a forecast.*"
            )

            if any(term in lower for term in [
                "wear winter clothes",
                "wear warm clothes",
                "what should i wear",
                "need a jacket",
                "need a coat",
                "is it cold",
            ]):
                temp = data.get("temperature")

                if temp is not None and temp <= 5:
                    clothing = (
                        "It's cold. A warm winter coat and layers "
                        "are sensible, especially if you'll be outside "
                        "for a while."
                    )
                elif temp is not None and temp <= 12:
                    clothing = (
                        "It's chilly. A jacket or coat with layers "
                        "is a good choice. Heavy winter clothing may "
                        "not be necessary unless you feel cold easily "
                        "or will be outside for a long time."
                    )
                elif temp is not None and temp <= 18:
                    clothing = (
                        "A light or medium jacket and layers should "
                        "usually be enough. You may not need heavy "
                        "winter clothing during the day."
                    )
                else:
                    clothing = (
                        "Heavy winter clothing may not be necessary "
                        "for these temperatures. Consider a light layer "
                        "and check the forecast before going out."
                    )

                answers.append(f"**What to wear:** {clothing}")

        elif tool == "time":
            answers.append(
                f"### Local time in {data['location']}\n"
                f"- **Date and time:** {data['date_time']}\n"
                f"- **Day:** {data['day_of_week'] or 'Not provided'}\n"
                f"- **Time zone:** {data['timezone']}"
            )

        elif tool == "currency":
            answers.append(
                f"### Currency conversion\n"
                f"**{format_number(data['amount'], 2)} "
                f"{data['from_currency']} = "
                f"{format_number(data['converted_amount'], 2)} "
                f"{data['to_currency']}**\n\n"
                f"- **Exchange rate:** 1 {data['from_currency']} = "
                f"{format_number(data['rate'], 6)} {data['to_currency']}\n"
                f"- **Rate date:** {data.get('rate_date') or 'Not provided'}\n\n"
                f"*{data.get('note', 'The rate may differ from your provider rate.')}*"
            )

    return "\n\n".join(answers) if answers else (
        "No results were returned by the available services."
    )


# =========================================================
# 11. STREAMLIT CHAT INTERFACE
# =========================================================

if "messages" not in st.session_state:
    st.session_state.messages = []

if "last_tool_results" not in st.session_state:
    st.session_state.last_tool_results = []

with st.sidebar:
    st.subheader("Agent controls")
    st.write(f"**Local model:** {MODEL_NAME}")
    st.write("**Available tools:**")
    st.write("- Weather")
    st.write("- World time")
    st.write("- Currency conversion")

    st.caption(
        "This version routes common requests directly to services. "
        "Conversation history lasts for the current session."
    )

    if st.button("Clear conversation"):
        st.session_state.messages = []
        st.session_state.last_tool_results = []
        st.rerun()

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

prompt = st.chat_input(
    "Ask about weather, time, or currency..."
)

if prompt:
    prior_messages = list(st.session_state.messages)

    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Understanding your request..."):
                resolved_question, calls, clarification = route_question(
                    prompt,
                    prior_messages,
                )

            if resolved_question.strip() != prompt.strip():
                st.caption(f"Interpreted question: {resolved_question}")

            if clarification:
                answer = clarification
                st.markdown(answer)

            elif not calls:
                answer = (
                    "I couldn't identify a supported request. "
                    "Try asking about weather, time, or currency conversion."
                )
                st.markdown(answer)

            else:
                st.caption(
                    "Selected tools: "
                    + ", ".join(call["tool"] for call in calls)
                )

                with st.spinner("Calling external services..."):
                    results = execute_tools(calls)

                st.session_state.last_tool_results = results

                answer = answer_from_results(
                    resolved_question,
                    results,
                )

                st.markdown(answer)

                with st.expander("Inspect tool calls and API results"):
                    st.markdown("**Interpreted question**")
                    st.write(resolved_question)

                    st.markdown("**Tool calls**")
                    st.json(calls)

                    st.markdown("**API results**")
                    st.json(results)

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
            })

        except Exception as error:
            answer = (
                "Something went wrong while processing your request. "
                "Check the technical details below."
            )

            st.error(answer)
            st.code(
                f"{type(error).__name__}: {error}",
                language="text",
            )

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
            })