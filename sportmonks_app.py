import streamlit as st
import pandas as pd
import requests
import os
import json
from datetime import datetime

# --- CONFIGURATION & DOCUMENTATION-VERIFIED LEAGUE DICTIONARY ---
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

# Mapping metrics to official Sportmonks v3 Statistics Type IDs
# Derived explicitly from Sportmonks v3 Statistics Definitions Documentation
STATS_MAP = {
    "goals": 52,
    "goalkeeper_saves": 80,
    "shots_on_target": 86,
    "big_chances_created": 194,
    "corner_kicks": 34,
    "crosses": 77,
    "accurate_crosses": 156,
    "accurate_long_passes": 144,
    "dribbles_percentage": 134,
    "ground_duels_percentage": 160,
    "aerial_duels_percentage": 161,
    "tackles": 78,
    "tackles_won": 172,
    "xg": 182,
    "xgot": 183,
    "xg_set_play": 185,
    "xg_open_play": 184
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
        st.success("CSV cache cleared. Progress tracking logs preserved.")

# --- UTILITIES GROUNDED IN SPORTMONKS V3 RESPONSE GEOMETRY ---
def safe_pct(numerator, denominator):
    if not denominator or denominator == 0:
        return 0
    return round((numerator / denominator) * 100)

def extract_metric(statistics_array, location, stat_name):
    """
    Parses flat statistics arrays exactly matching the Sportmonks v3 JSON schema layout:
    { "type_id": ID, "location": "home"/"away", "data": { "value": X } }
    """
    target_type_id = STATS_MAP.get(stat_name)
    if not statistics_array:
        return 0
        
    for entry in statistics_array:
        if entry.get("type_id") == target_type_id and entry.get("location") == location:
            data_obj = entry.get("data", {})
            if data_obj and "value" in data_obj:
                return data_obj.get("value") or 0
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
            
            # Step 1: Request Seasons via explicit param dictionary mapping
            seasons_url = "https://sportmonks.com"
            query_params = {"filter[leagues]": str(league_id)}
            
            try:
                res = requests.get(seasons_url, headers=headers, params=query_params)
                
                # Intercept plan coverage restrictions gracefully
                if res.status_code == 403:
                    st.error(f"🚫 **Plan Restriction (403):** Your subscription tier does not cover {league_label}. Skipping league.")
                    continue
                elif res.status_code != 200:
                    st.error(f"Failed to fetch seasons for league {league_id}. HTTP Status: {res.status_code}")
                    continue
                    
                seasons_data = res.json().get("data", [])
            except Exception as e:
                st.error(f"Network error on seasons fetch: {str(e)}")
                continue
                
            # Filter newest relative seasons descending based on lookback constraint configuration
            seasons_data = sorted(seasons_data, key=lambda x: x.get("id", 0), reverse=True)[:seasons_lookback + 1]
            season_ids = [s["id"] for s in seasons_data]
            
            # Step 2: Establish data compilation file path infrastructure
            csv_path = os.path.join(STORAGE_DIR, f"league_{league_id}.csv")
            existing_df = pd.read_csv(csv_path) if os.path.exists(csv_path) else pd.DataFrame()
            completed_fixtures = progress_store.get(str(league_id), [])
            
            all_fixtures = []
            for s_id in season_ids:
                fix_url = "https://sportmonks.com"
                fixture_params = {
                    "filter[seasons]": str(s_id),
                    "include": "statistics;participants"
                }
                try:
                    res_fix = requests.get(fix_url, headers=headers, params=fixture_params)
                    if res_fix.status_code == 403:
                        continue
                    if res_fix.status_code == 200:
                        all_fixtures.extend(res_fix.json().get("data", []))
                except Exception:
                    pass
            
            total_matches = len(all_fixtures)
            if total_matches == 0:
                st.info("No authorized fixture data discovered or available for this selection.")
                continue
                
            progress_bar = st.progress(0)
            status_text = st.empty()
            new_rows = []
            for idx, fix in enumerate(all_fixtures):
                fix_id = fix["id"]
                # Display exact real-time counter metric (Matches Requested out of Total)
                status_text.text(f"Match progress counter: {idx + 1} requested out of {total_matches} available")
                progress_bar.progress((idx + 1) / total_matches)
                
                # Interruption recovery check: Skip if previously logged to storage
                if str(fix_id) in completed_fixtures:
                    continue
                
                date_str = fix.get("starting_at", "9999-12-31")[:10]
                season_obj = next((s for s in seasons_data if s["id"] == fix.get("season_id")), {})
                season_name = str(season_obj.get("name", "Unknown"))
                
                participants = fix.get("participants", [])
                home_team = next((p for p in participants if p.get("meta", {}).get("location") == "home"), {})
                away_team = next((p for p in participants if p.get("meta", {}).get("location") == "away"), {})
                
                h_name = home_team.get("name", "Home Side")
                a_name = away_team.get("name", "Away Side")
                
                stats = fix.get("statistics", [])
                
                # Schema extraction via flat arrays alignment mapping rules
                h_goals = extract_metric(stats, "home", "goals")
                a_goals = extract_metric(stats, "away", "goals")
                h_saves = extract_metric(stats, "home", "goalkeeper_saves")
                a_saves = extract_metric(stats, "away", "goalkeeper_saves")
                h_sot = extract_metric(stats, "home", "shots_on_target")
                a_sot = extract_metric(stats, "away", "shots_on_target")
                h_big_ch = extract_metric(stats, "home", "big_chances_created")
                a_big_ch = extract_metric(stats, "away", "big_chances_created")
                h_corners = extract_metric(stats, "home", "corner_kicks")
                a_corners = extract_metric(stats, "away", "corner_kicks")
                h_cross = extract_metric(stats, "home", "crosses")
                a_cross = extract_metric(stats, "away", "crosses")
                h_acc_cross = extract_metric(stats, "home", "accurate_crosses")
                a_acc_cross = extract_metric(stats, "away", "accurate_crosses")
                h_acc_long = extract_metric(stats, "home", "accurate_long_passes")
                a_acc_long = extract_metric(stats, "away", "accurate_long_passes")
                
                # Percentage metrics rounded off directly to nearest whole integers
                h_drib_pct = round(extract_metric(stats, "home", "dribbles_percentage"))
                a_drib_pct = round(extract_metric(stats, "away", "dribbles_percentage"))
                h_ground = round(extract_metric(stats, "home", "ground_duels_percentage"))
                a_ground = round(extract_metric(stats, "away", "ground_duels_percentage"))
                h_aerial = round(extract_metric(stats, "home", "aerial_duels_percentage"))
                a_aerial = round(extract_metric(stats, "away", "aerial_duels_percentage"))
                
                h_tackles = extract_metric(stats, "home", "tackles")
                a_tackles = extract_metric(stats, "away", "tackles")
                h_tackles_w = extract_metric(stats, "home", "tackles_won")
                a_tackles_w = extract_metric(stats, "away", "tackles_won")
                
                # Math code processing calculated percentages
                h_cross_pct = safe_pct(h_acc_cross, h_cross)
                a_cross_pct = safe_pct(a_acc_cross, a_cross)
                h_tack_pct = safe_pct(h_tackles_w, h_tackles)
                a_tack_pct = safe_pct(a_tackles_w, a_tackles)
                
                # Decimal xG explicit configurations
                h_xg = round(float(extract_metric(stats, "home", "xg") or 0.0), 2)
                a_xg = round(float(extract_metric(stats, "away", "xg") or 0.0), 2)
                h_xgot = round(float(extract_metric(stats, "home", "xgot") or 0.0), 2)
                a_xgot = round(float(extract_metric(stats, "away", "xgot") or 0.0), 2)
                h_xg_set = round(float(extract_metric(stats, "home", "xg_set_play") or 0.0), 2)
                a_xg_set = round(float(extract_metric(stats, "away", "xg_set_play") or 0.0), 2)
                h_xg_open = round(float(extract_metric(stats, "home", "xg_open_play") or 0.0), 2)
                a_xg_open = round(float(extract_metric(stats, "away", "xg_open_play") or 0.0), 2)
                
                # Side-by-side array alignment mapping configurations
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
            
            # File system appending, clearing duplication layers and sorting chronologically
            if new_rows:
                new_df = pd.DataFrame(new_rows)
                combined_df = pd.concat([existing_df, new_df], ignore_index=True).drop_duplicates()
                combined_df['date'] = pd.to_datetime(combined_df['date'])
                combined_df = combined_df.sort_values(by='date', ascending=True)
                combined_df.to_csv(csv_path, index=False)
                
                progress_store[str(league_id)] = completed_fixtures
                save_progress(progress_store)
                
            st.success(f"Successfully processed database file cache: league_{league_id}.csv")

# --- DOWNLOAD CENTRE ---
st.markdown("---")
st.header("📥 Complete & Interrupted Downloads Center")
csv_files = [f for f in os.listdir(STORAGE_DIR) if f.endswith(".csv")]

if csv_files:
    for file in csv_files:
        file_path = os.path.join(STORAGE_DIR, file)
        df_download = pd.read_csv(file_path)
        
        st.download_button(
            label=f"⬇️ Download Aggregated League Table ({file})",
            data=df_download.to_csv(index=False),
            file_name=file,
            mime='text/csv'
        )
else:
    st.info("No compiled CSV database files discovered inside persistent directory yet.")
