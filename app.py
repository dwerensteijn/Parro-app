import base64
from datetime import date, datetime, time
import json
import os
import urllib.parse
from openai import OpenAI
import streamlit as st

# ------------------------------------------------------------------------------
# PAGE SETUP & STYLING
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="Parro naar Google Calendar & .ics", page_icon="📅", layout="wide"
)

st.markdown(
    """
<style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #64748B;
        margin-bottom: 2rem;
    }
    .gcal-btn {
        display: inline-block;
        background-color: #4285F4;
        color: white !important;
        padding: 8px 16px;
        border-radius: 6px;
        text-decoration: none;
        font-weight: 500;
        margin-top: 6px;
        margin-bottom: 6px;
    }
    .gcal-btn:hover {
        background-color: #3367D6;
    }
</style>
""",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="main-header">📅 Parro Kalender Sync</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="sub-header">Zet screenshots van de Parro-schoolkalender om naar Google Calendar-afspraken en .ics-bestanden.</div>',
    unsafe_allow_html=True,
)

# ------------------------------------------------------------------------------
# SIDEBAR - CONFIGURATIE
# ------------------------------------------------------------------------------
with st.sidebar:
  st.header("⚙️ Instellingen")

  # API Key afhandeling (via Streamlit Secrets of handmatige invoer)
  default_key = (
      st.secrets.get("OPENAI_API_KEY", "") if hasattr(st, "secrets") else ""
  )
  api_key = st.text_input(
      "OpenAI API Key",
      value=default_key,
      type="password",
      help="Voer je OpenAI API-sleutel in.",
  )

  selected_model = st.selectbox(
      "AI Model",
      ["gpt-4o", "gpt-4o-mini"],
      index=0,
      help="gpt-4o is het meest nauwkeurig voor het uitlezen van screenshots.",
  )

  st.markdown("---")
  st.markdown("### 💡 Hoe het werkt")
  st.markdown("""
    1. Upload een screenshot van de **Parro** kalender/agenda.
    2. De Vision AI herkent automatisch titels, datums en tijden.
    3. Controleer of bewerk de voorgestelde afspraken.
    4. Voeg ze toe aan **Google Calendar** of download het **.ics**-bestand.
    """)


# ------------------------------------------------------------------------------
# HULPFUNCTIES
# ------------------------------------------------------------------------------
def encode_image(image_bytes):
  return base64.b64encode(image_bytes).decode("utf-8")


def parse_parro_screenshot(image_bytes, api_key, model_name="gpt-4o"):
  client = OpenAI(api_key=api_key)
  base64_image = encode_image(image_bytes)
  current_year = datetime.now().year

  system_prompt = f"""
    Je bent een assistent die screenshots van de school-app Parro analyseert.
    Extraheer alle unieke kalenderafspraken/agenda-items uit het screenshot.
    
    Context:
    - Het huidige jaar is {current_year}. Als een datum geen jaartal bevat, neem aan dat het {current_year} is (of {current_year + 1} als de maand al voorbij is).
    - Zorg voor een correct ISO-datumformaat: YYYY-MM-DD.
    - Zorg voor een correct 24-uurs tijdformaat: HH:MM. Als er geen specifieke tijd staat, gebruik dan "08:30" als begintijd en "15:00" als eindtijd.
    - Maak de titels helder en kort (bijv. "Schoolreisje Groep 3 & 4", "Studiedag - Leerlingen vrij", "Luizencontrole").
    
    Geef je antwoord UITSLUITEND in geldig JSON met dit exacte schema:
    {{
      "events": [
        {{
          "title": "Titel van de activiteit",
          "date": "YYYY-MM-DD",
          "start_time": "HH:MM",
          "end_time": "HH:MM",
          "description": "Eventuele aanvullende details, locaties of opmerkingen"
        }}
      ]
    }}
    """

  response = client.chat.completions.create(
      model=model_name,
      messages=[
          {
              "role": "system",
              "content": (
                  "Je bent een JSON-only extractor van kalendergegevens uit"
                  " afbeeldingen."
              ),
          },
          {
              "role": "user",
              "content": [
                  {"type": "text", "text": system_prompt},
                  {
                      "type": "image_url",
                      "image_url": {
                          "url": f"data:image/jpeg;base64,{base64_image}"
                      },
                  },
              ],
          },
      ],
      response_format={"type": "json_object"},
      temperature=0.1,
  )

  raw_json = response.choices[0].message.content
  data = json.loads(raw_json)
  return data.get("events", [])


def generate_gcal_url(
    title, date_str, start_time_str, end_time_str, description=""
):
  try:
    start_dt = datetime.strptime(
        f"{date_str} {start_time_str}", "%Y-%m-%d %H:%M"
    )
    end_dt = datetime.strptime(f"{date_str} {end_time_str}", "%Y-%m-%d %H:%M")

    start_formatted = start_dt.strftime("%Y%m%dT%H%M%S")
    end_formatted = end_dt.strftime("%Y%m%dT%H%M%S")

    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{start_formatted}/{end_formatted}",
        "details": description,
    }
    return f"https://calendar.google.com/calendar/render?{urllib.parse.urlencode(params)}"
  except Exception:
    return "#"


def generate_ics_content(events_list):
  ics_lines = [
      "BEGIN:VCALENDAR",
      "VERSION:2.0",
      "PRODID:-//Parro Calendar Sync App//NL",
      "CALSCALE:GREGORIAN",
      "METHOD:PUBLISH",
  ]

  for ev in events_list:
    try:
      start_dt = datetime.strptime(
          f"{ev['date']} {ev['start_time']}", "%Y-%m-%d %H:%M"
      )
      end_dt = datetime.strptime(
          f"{ev['date']} {ev['end_time']}", "%Y-%m-%d %H:%M"
      )

      dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
      dtend = end_dt.strftime("%Y%m%dT%H%M%S")
      now_str = datetime.now().strftime("%Y%m%dT%H%M%SZ")

      title_clean = ev["title"].replace(",", "\\,").replace(";", "\\;")
      desc_clean = (
          ev.get("description", "")
          .replace("\n", "\\n")
          .replace(",", "\\,")
          .replace(";", "\\;")
      )

      ics_lines.extend([
          "BEGIN:VEVENT",
          (
              f"UID:parro-{start_dt.strftime('%Y%m%d%H%M%S')}-{hash(title_clean)}@parrosync.app"
          ),
          f"DTSTAMP:{now_str}",
          f"DTSTART:{dtstart}",
          f"DTEND:{dtend}",
          f"SUMMARY:{title_clean}",
          f"DESCRIPTION:{desc_clean}",
          "STATUS:CONFIRMED",
          "END:VEVENT",
      ])
    except Exception:
      continue

  ics_lines.append("END:VCALENDAR")
  return "\r\n".join(ics_lines)


# ------------------------------------------------------------------------------
# HOOFDLAYOUT
# ------------------------------------------------------------------------------
col_upload, col_preview = st.columns([1, 1], gap="large")

with col_upload:
  st.subheader("1. Upload Parro Screenshot")
  uploaded_file = st.file_uploader(
      "Kies een afbeelding", type=["png", "jpg", "jpeg", "webp"]
  )

  if uploaded_file:
    st.image(
        uploaded_file,
        caption="Geüpload Parro screenshot",
        use_container_width=True,
    )

with col_preview:
  st.subheader("2. AI Herkenning")

  if uploaded_file:
    if not api_key:
      st.warning(
          "⚠️ Voer eerst je OpenAI API Key in de sidebar in om de afbeelding te"
          " analyseren."
      )
    else:
      if (
          "extracted_events" not in st.session_state
          or st.session_state.get("last_uploaded") != uploaded_file.name
      ):
        with st.spinner("🔍 Screenshot wordt geanalyseerd door AI..."):
          try:
            events = parse_parro_screenshot(
                uploaded_file.getvalue(), api_key, selected_model
            )
            st.session_state["extracted_events"] = events
            st.session_state["last_uploaded"] = uploaded_file.name
            st.success(f"✅ {len(events)} agenda-item(s) gevonden!")
          except Exception as e:
            st.error(f"Fout bij analyse: {e}")
            st.session_state["extracted_events"] = []

# ------------------------------------------------------------------------------
# BEWERK- EN SELECTIE-INTERACTION
# ------------------------------------------------------------------------------
if "extracted_events" in st.session_state and st.session_state["extracted_events"]:
  events = st.session_state["extracted_events"]

  st.markdown("---")
  st.subheader("3. Selecteer & Controleer Items")

  select_all = st.checkbox("Selecteer alles / Deselecteer alles", value=True)
  selected_events = []

  for idx, ev in enumerate(events):
    with st.container():
      col_chk, col_details = st.columns([0.08, 0.92])

      with col_chk:
        is_selected = st.checkbox("", value=select_all, key=f"chk_{idx}")

      with col_details:
        col_t, col_d, col_s, col_e = st.columns([2.5, 1.2, 1, 1])

        with col_t:
          mod_title = st.text_input(
              "Titel",
              value=ev.get("title", ""),
              key=f"title_{idx}",
              label_visibility="collapsed",
          )
        with col_d:
          try:
            default_date = datetime.strptime(
                ev.get("date", str(date.today())), "%Y-%m-%d"
            ).date()
          except ValueError:
            default_date = date.today()
          mod_date = st.date_input(
              "Datum",
              value=default_date,
              key=f"date_{idx}",
              label_visibility="collapsed",
          )
        with col_s:
          mod_start = st.text_input(
              "Start",
              value=ev.get("start_time", "08:30"),
              key=f"start_{idx}",
              label_visibility="collapsed",
          )
        with col_e:
          mod_end = st.text_input(
              "Eind",
              value=ev.get("end_time", "15:00"),
              key=f"end_{idx}",
              label_visibility="collapsed",
          )

        mod_desc = st.text_input(
            "Toelichting",
            value=ev.get("description", ""),
            key=f"desc_{idx}",
            placeholder="Toelichting / Locatie",
        )

        if is_selected:
          selected_events.append({
              "title": mod_title,
              "date": mod_date.strftime("%Y-%m-%d"),
              "start_time": mod_start,
              "end_time": mod_end,
              "description": mod_desc,
          })
    st.markdown(
        "<hr style='margin: 8px 0; border-top: 1px dashed #cbd5e1;'>",
        unsafe_allow_html=True,
    )

  # ------------------------------------------------------------------------------
  # EXPORT OPTIES
  # ------------------------------------------------------------------------------
  st.markdown("### 4. Exporteren")

  if not selected_events:
    st.info("Selecteer ten minste één item om te exporteren.")
  else:
    col_gcal, col_ics = st.columns(2)

    with col_gcal:
      st.markdown("#### 🌐 Toevoegen aan Google Calendar")
      st.caption("Klik op de knop om het item direct in je agenda te openen:")

      for item in selected_events:
        url = generate_gcal_url(
            item["title"],
            item["date"],
            item["start_time"],
            item["end_time"],
            item["description"],
        )
        st.markdown(
            f"👉 <a href='{url}' target='_blank' class='gcal-btn'>➕"
            f" {item['title']} ({item['date']})</a>",
            unsafe_allow_html=True,
        )

    with col_ics:
      st.markdown("#### 📥 Alles in 1x exporteren (.ics)")
      st.caption(
          "Download een `.ics` bestand voor import in Apple Calendar, Outlook of"
          " Google Calendar:"
      )

      ics_data = generate_ics_content(selected_events)
      st.download_button(
          label="📥 Download .ics Bestand",
          data=ics_data,
          file_name="parro_agenda_items.ics",
          mime="text/calendar",
          type="primary",
          use_container_width=True,
      )
else:
  if not uploaded_file:
    st.info("👋 Upload een Parro screenshot aan de linkerkant om te beginnen.")
