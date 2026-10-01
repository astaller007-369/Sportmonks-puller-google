import streamlit as st
import pandas as pd
import requests
import os
import json
from datetime import datetime

# --- CONFIGURATION & LEAGUE DICTIONARY ---
# Mapped using exact provided IDs for verification
LEAGUES_DICT = {
    "Poland: Ekstraklasa": 453, "Brazil: Serie A": 648, "Germany: Bundesliga": 82, "Germany: 2. Bundesliga": 85,
    "France: Ligue 1": 301, "France: Ligue 2": 304, "Portugal: Liga Portugal": 462, "Spain: La Liga": 564,
    "Spain: La Liga 2": 567, "Netherlands: Eredivisie": 72, "Argentina: Liga Profesional de Futbol": 636,
    "Sweden: Allsvenskan": 573, "Greece: Super League": 325, "Switzerland: Super League": 591,
    "Australia: A-League Men": 1356, "Austria: Admiral Bundesliga": 181, "Russia: Premier League": 486,
    "Italy: Serie A": 384, "Italy: Serie B": 387, "Denmark: Superliga": 271, "Colombia: Liga Betplay": 672,
    "Turkey: Super Lig": 600, "Republic of Ireland: Premier Division": 360, "England: Premier League": 8,
    "England: Championship": 9, "Japan: J1 League": 968, "Belgium: Pro League": 208, "Belgium: Challenger Pro League": 211,
    "Scotland: Premiership": 501, "Norway: Eliteserien": 444, "India: Indian Super League": 1007,
    "Egypt: Premier League": 830, "South Africa: Premier League": 806, "Thailand: Thai Premier League": 1064,
    "Mexico: Liga MX": 743, "United States: Major League Soccer": 779, "Saudi Arabia: Pro League": 944,
    "Brazil: Serie B": 651, "South Korea: K League 1": 1034, "England: League One": 12, "England: League Two": 14,
    "Netherlands: Eerste Divisie": 73, "Croatia: HNL": 214
}

STORAGE_DIR = "sportmonks_data"
os.makedirs(STORAGE_DIR, exist_ok=True)
PROGRESS_FILE = os.path.join(STORAGE_DIR, "fetch_progress.json")

st.set_page_config(page_title="Sportmonks Sports Data Aggregator", layout="wide")
st.title("⚽ Sportmonks Football Data Downloader")

# --- PERSISTENT STORAGE MANAGEMENT ---
def load_progress():
    if os.path.exists(PROGRESS_FILE):
        with open(PROGRESS_FILE, "r") as f:
            return json.load(f)
    return {}

def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f)

progress_store = load_progress()

# --- SIDEBAR UI CONTROLS ---
with st.sidebar:
    st.header("🔑 Authentication & Setup")
    api_key = st.text_input("Sportmonks API Key", type="password", help="Enter your Sportmonks v3 API token")
    
    current_year = datetime.now().year
    seasons_lookback = st.slider("Lookback Seasons (from current)", 0, 7, 1)
    
    st.subheader("🏆 League Selection")
    col1, col2 = st.columns(2)
    if col1.button("Select All Leagues"):
        st.session_state.selected_leagues = list(LEAGUES_DICT.keys())
    if col2.button("Clear All Selection"):
        st.session_state.selected_leagues = []
        
    selected_leagues = st.multiselect(
        "Choose Leagues to process:", 
        options=list(LEAGUES_DICT.keys()), 
        key="selected_leagues"
    )

    st.subheader("🧹 Storage Management")
    if st.button("Partial Clear (Keep Progress, Free Space)"):
        files = [f for f in os.listdir(STORAGE_DIR) if f.endswith(".csv")]
        for f in files:
            os.remove(os.path.join(STORAGE_DIR, f))
        st.success("CSV cache cleared. Progress tracking preserved.")

# --- DATA EXTRACTION & MATH UTILITIES ---
def safe_pct(numerator, denominator):
    if not denominator or denominator == 0:
        return 0
    return round((numerator / denominator) * 100)

def extract_stat(stats_list, participant_id, name):
    for entry in stats_list:
        if entry.get("participant_id") == participant_id:
            for stat in entry.get("stats", []):
                if stat.get("type", {}).get("developer_name") == name:
                    val = stat.get("value", {}).get("all")
                    return val if val is not None else 0
    return 0
    # --- DATA PROCESSING PIPELINE ---
if st.button("🚀 Start / Resume Data Fetching"):
    if not api_key:
        st.error("Please enter a valid API Key first.")
    elif not selected_leagues:
        st.warning("Please select at least one league.")
    else:
        headers = {"Authorization": api_key}
        
        for league_label in selected_leagues:
            league_id = LEAGUES_DICT[league_label]
            st.markdown(f"### Processing: **{league_label} (ID: {league_id})**")
            
            # Step 1: Fetch Seasons
            seasons_url = f"https://sportmonks.com[leagues]={league_id}"
            try:
                res = requests.get(seasons_url, headers=headers)
                if res.status_code != 200:
                    st.error(f"Failed to fetch seasons for league {league_id}. Skipping.")
                    continue
                seasons_data = res.json().get("data", [])
            except Exception as e:
                st.error(f"Network error on seasons fetch: {str(e)}")
                continue
                
            # Filter based on user lookback choice (sorted descending by standard order)
            seasons_data = sorted(seasons_data, key=lambda x: x.get("id", 0), reverse=True)[:seasons_lookback + 1]
            season_ids = [s["id"] for s in seasons_data]
            
            # Step 2: Fetch and build unique items tracker
            csv_path = os.path.join(STORAGE_DIR, f"league_{league_id}.csv")
            existing_df = pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame()
            completed_fixtures = progress_store.get(str(league_id), [])
            
            all_fixtures = []
            for s_id in season_ids:
                fix_url = f"https://sportmonks.com[seasons]={s_id}&include=statistics;participants"
                try:
                    res_fix = requests.get(fix_url, headers=headers)
                    if res_fix.status_code == 200:
                        all_fixtures.extend(res_fix.json().get("data", []))
                except Exception:
                    pass
            
            total_matches = len(all_fixtures)
            if total_matches == 0:
                st.info("No matches found for selected seasons configuration.")
                continue
                
            progress_bar = st.progress(0)
            status_text = st.empty()
            new_rows = []
            
            for idx, fix in enumerate(all_fixtures):
                fix_id = fix["id"]
                status_text.text(f"Match status: {idx + 1} / {total_matches} entries checked")
                progress_bar.progress((idx + 1) / total_matches)
                
                # Check if it was processed already to resume efficiently
                if str(fix_id) in completed_fixtures:
                    continue
                
                date_str = fix.get("starting_at", "9999-12-31")[:10]
                season_obj = next((s for s in seasons_data if s["id"] == fix.get("season_id")), {})
                season_name = str(season_obj.get("name", "Unknown"))
                
                participants = fix.get("participants", [])
                home_team = next((p for p in participants if p.get("meta", {}).get("location") == "home"), {})
                away_team = next((p for p in participants if p.get("meta", {}).get("location") == "away"), {})
                
                h_id, h_name = home_team.get("id"), home_team.get("name", "Home Team")
                a_id, a_name = away_team.get("id"), away_team.get("name", "Away Team")
                
                stats = fix.get("statistics", [])
                
                # Metric values extraction
                h_goals = extract_stat(stats, h_id, "GOALS")
                a_goals = extract_stat(stats, a_id, "GOALS")
                h_saves = extract_stat(stats, h_id, "GOALKEEPER_SAVES")
                a_saves = extract_stat(stats, a_id, "GOALKEEPER_SAVES")
                h_sot = extract_stat(stats, h_id, "SHOTS_ON_TARGET")
                a_sot = extract_stat(stats, a_id, "SHOTS_ON_TARGET")
                h_big_ch = extract_stat(stats, h_id, "BIG_CHANCES_CREATED")
                a_big_ch = extract_stat(stats, a_id, "BIG_CHANCES_CREATED")
                h_corners = extract_stat(stats, h_id, "CORNER_KICKS")
                a_corners = extract_stat(stats, a_id, "CORNER_KICKS")
                h_cross = extract_stat(stats, h_id, "CROSSES")
                a_cross = extract_stat(stats, a_id, "CROSSES")
                h_acc_cross = extract_stat(stats, h_id, "ACCURATE_CROSSES")
                a_acc_cross = extract_stat(stats, a_id, "ACCURATE_CROSSES")
                h_acc_long = extract_stat(stats, h_id, "ACCURATE_LONG_PASSES")
                a_acc_long = extract_stat(stats, a_id, "ACCURATE_LONG_PASSES")
                h_drib_pct = round(extract_stat(stats, h_id, "DRIBBLES_PERCENTAGE"))
                a_drib_pct = round(extract_stat(stats, a_id, "DRIBBLES_PERCENTAGE"))
                h_ground = round(extract_stat(stats, h_id, "GROUND_DUELS_PERCENTAGE"))
                a_ground = round(extract_stat(stats, a_id, "GROUND_DUELS_PERCENTAGE"))
                h_aerial = round(extract_stat(stats, h_id, "AERIAL_DUELS_PERCENTAGE"))
                a_aerial = round(extract_stat(stats, a_id, "AERIAL_DUELS_PERCENTAGE"))
                h_tackles = extract_stat(stats, h_id, "TACKLES")
                a_tackles = extract_stat(stats, a_id, "TACKLES")
                h_tackles_w = extract_stat(stats, h_id, "TACKLES_WON")
                a_tackles_w = extract_stat(stats, a_id, "TACKLES_WON")
                
                # Math calculation properties
                h_cross_pct = safe_pct(h_acc_cross, h_cross)
                a_cross_pct = safe_pct(a_acc_cross, a_cross)
                h_tack_pct = safe_pct(h_tackles_w, h_tackles)
                a_tack_pct = safe_pct(a_tackles_w, a_tackles)
                
                # Decimal xG configurations
                h_xg = round(float(extract_stat(stats, h_id, "EXPECTED_GOALS") or 0.0), 2)
                a_xg = round(float(extract_stat(stats, a_id, "EXPECTED_GOALS") or 0.0), 2)
                h_xgot = round(float(extract_stat(stats, h_id, "EXPECTED_GOALS_ON_TARGET") or 0.0), 2)
                a_xgot = round(float(extract_stat(stats, a_id, "EXPECTED_GOALS_ON_TARGET") or 0.0), 2)
                h_xg_set = round(float(extract_stat(stats, h_id, "XG_SET_PLAY") or 0.0), 2)
                a_xg_set = round(float(extract_stat(stats, a_id, "XG_SET_PLAY") or 0.0), 2)
                h_xg_open = round(float(extract_stat(stats, h_id, "XG_OPEN_PLAY") or 0.0), 2)
                a_xg_open = round(float(extract_stat(stats, a_id, "XG_OPEN_PLAY") or 0.0), 2)
                
                row = {
                    "league_country": league_label, "season": season_name, "date": date_str,
                    "team": f"({h_name},{a_name})", "goals": f"({h_goals},{a_goals})",
                    "goalkeeper_saves": f"({h_saves},{a_saves})", "shots_on_target": f"({h_sot},{a_sot})",
                    "big_chances_created": f"({h_big_ch},{a_big_ch})", "corner_kicks": f"({h_corners},{a_corners})",
                    "crosses": f"({h_cross},{a_cross})", "accurate_crosses": f"({h_acc_cross},{a_acc_cross})",
                    "successful_crosses_percentage": f"({h_cross_pct}%,{a_cross_pct}%)",
                    "accurate_long_passes": f"({h_acc_long},{a_acc_long})",
                    "dribbles_percentage": f"({h_drib_pct}%,{a_drib_pct}%)",
                    "ground_duels_percentage": f"({h_ground}%,{a_ground}%)",
                    "aerial_duels_percentage": f"({h_aerial}%,{a_aerial}%)",
                    "tackles": f"({h_tackles},{a_tackles})", "tackles_won": f"({h_tackles_w},{a_tackles_w})",
                    "tackles_won_percentage": f"({h_tack_pct}%,{a_tack_pct}%)",
                    "xg": f"({h_xg},{a_xg})", "xgot": f"({h_xgot},{a_xgot})",
                    "xg_set_play": f"({h_xg_set},{a_xg_set})", "xg_open_play": f"({h_xg_open},{a_xg_open})"
                }
                new_rows.append(row)
                completed_fixtures.append(str(fix_id))
            
            # Storage appending and ordering update
            if new_rows:
                new_df = pd.DataFrame(new_rows)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True).drop_duplicates()
                combined_df['date'] = pd.to_datetime(combined_df['date'])
                combined_df = combined_df.sort_values(by='date', ascending=True)
                combined_df.to_csv(csv_path, index=False)
                
                progress_store[str(league_id)] = completed_fixtures
                save_progress(progress_store)
                
            st.success(f"Successfully processed table file: league_{league_id}.csv")

# --- DOWNLOAD CENTRE ---
st.markdown("---")
st.header("📥 Complete & Interrupted Downloads Center")
csv_files = [f for f in os.listdir(STORAGE_DIR) if f.endswith(".csv")]

if csv_files:
    for file in csv_files:
        file_path = os.path.join(STORAGE_DIR, file)
        df_download = pd.read_csv(file_path)
        
        st.download_button(
            label=f"⬇️ Download Data Table ({file})",
            data=df_download.to_csv(index=False),
            file_name=file,
            mime='text/csv'
        )
else:
    st.info("No compiled database tables found in persistent directory storage yet.")
    