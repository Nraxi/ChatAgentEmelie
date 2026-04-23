import warnings
warnings.filterwarnings("ignore")

import ollama
import subprocess
import json
import re
import os
import requests
from bs4 import BeautifulSoup
from ddgs import DDGS

HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

try:
    import gnureadline as readline
except ImportError:
    try:
        import readline
    except ImportError:
        try:
            import pyreadline3 as readline
        except ImportError:
            readline = None


# ---------------- CONFIG ----------------

MODEL_NAME    = "gemma4:e4b"
AGENT_NAME    = "Emelie"
chat_history  = []
current_project = {"path": None}  # aktivt VS Code-projekt
current_track = {"query": None, "uri": None}
HISTORY_FILE  = "emelie_history.json"
CACHE_FILE    = "emelie_cache.json"
CACHE_TTL_H   = 24



# ---------------- PERSISTENT HISTORY ----------------

def load_history():
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_history(history):
    try:
        clean = [m for m in history if m.get("content", "").strip()]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(clean[-40:], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


# ---------------- SEARCH CACHE ----------------

def load_cache():
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def cache_get(cache, key):
    from datetime import datetime
    entry = cache.get(key)
    if not entry:
        return None
    age_h = (datetime.now().timestamp() - entry["ts"]) / 3600
    if age_h > CACHE_TTL_H:
        del cache[key]
        return None
    return entry["data"]

def cache_set(cache, key, data):
    from datetime import datetime
    cache[key] = {"ts": datetime.now().timestamp(), "data": data}


# ---------------- UTILS ----------------

def extract_json_safe(text):
    import ast
    text = re.sub(r'```json\s*|\s*```', '', text).strip()

    for match in re.finditer(r'\{.*?\}', text, re.DOTALL):
        raw = match.group(0)

        try:
            data = json.loads(raw)
            if "action" in data:
                return data
        except:
            pass

        try:
            data = ast.literal_eval(raw)
            if isinstance(data, dict) and "action" in data:
                return data
        except:
            continue

    return None


def extract_song(text):
    match = re.search(r'([A-Za-z0-9 &\']+)\s*[-–]\s*([A-Za-z0-9 &\']+)', text)
    return match.group(0).strip() if match else None


# ---------------- MUSIC CHARTS ----------------

BEATPORT_GENRES = {
    "hard techno":      "https://www.beatport.com/genre/hard-techno/2/top-100",
    "techno":           "https://www.beatport.com/genre/techno/6/top-100",
    "house":            "https://www.beatport.com/genre/house/5/top-100",
    "tech house":       "https://www.beatport.com/genre/tech-house/11/top-100",
    "trance":           "https://www.beatport.com/genre/trance/7/top-100",
    "drum and bass":    "https://www.beatport.com/genre/drum-and-bass/1/top-100",
    "dnb":              "https://www.beatport.com/genre/drum-and-bass/1/top-100",
    "dubstep":          "https://www.beatport.com/genre/dubstep/18/top-100",
    "hardstyle":        "https://www.beatport.com/genre/hardstyle/31/top-100",
    "ambient":          "https://www.beatport.com/genre/electronica/3/top-100",
    "electro":          "https://www.beatport.com/genre/electro-classic-detroit-modern/94/top-100",
    "melodic techno":   "https://www.beatport.com/genre/melodic-house-techno/90/top-100",
    "afro house":       "https://www.beatport.com/genre/afro-house/89/top-100",
}

def detect_genre_url(text):
    text_lower = text.lower()
    for genre, url in BEATPORT_GENRES.items():
        if genre in text_lower:
            return genre, url
    return None, None

def fetch_charts(url, genre, year=None):
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        soup = BeautifulSoup(r.text, "html.parser")

        rows = soup.find_all("div", class_=lambda c: c and "row" in c and "tracks-table" in c)
        all_tracks = []
        for row in rows:
            title_cell = row.find("div", class_=lambda c: c and "cell" in c and "title" in c)
            date_cell  = row.find("div", class_=lambda c: c and "cell" in c and "date" in c)
            if not title_cell:
                continue
            track_a     = title_cell.find("a", href=lambda h: h and "/track/" in h)
            artist_links = title_cell.find_all("a", href=lambda h: h and "/artist/" in h)
            if not track_a or not artist_links:
                continue
            title   = track_a.get("title") or track_a.get_text(strip=True)
            artists = ", ".join(a.get_text(strip=True) for a in artist_links)
            date    = date_cell.get_text(strip=True) if date_cell else ""
            all_tracks.append((artists, title, date))

        if year:
            filtered = [(a, t, d) for a, t, d in all_tracks if d.startswith(str(year))]
        else:
            filtered = all_tracks

        if not filtered and year:
            # inga exakta 2025-träffar — visa alla med datum
            lines = [f"#{i+1}: {a} - {t} ({d})" for i, (a, t, d) in enumerate(all_tracks[:20])]
            return "\n".join(lines)

        lines = [f"#{i+1}: {a} - {t}" for i, (a, t, _) in enumerate(filtered[:20])]
        return "\n".join(lines) if lines else ""

    except Exception:
        return ""


# ---------------- QUERY ----------------

def build_query(user_query):
    return f"{user_query} spotify 2025"


# ---------------- WEB SEARCH ----------------

_ddg_cache = {}

def web_search_ddg(query):
    if query in _ddg_cache:
        return _ddg_cache[query]
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
        if not results:
            return []
        out = [f"{r.get('body','')} ({r.get('href','')})" for r in results]
        _ddg_cache[query] = out
        return out
    except Exception:
        return []




def fetch_page(url, max_chars=2000):
    try:
        r = requests.get(url, headers=HEADERS, timeout=6)
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator=" ", strip=True)
        text = re.sub(r'\s+', ' ', text)
        return text[:max_chars]
    except Exception:
        return ""


def web_search_google(query):
    try:
        from googlesearch import search
        results = list(search(query, num_results=5, lang="sv"))
        return [url for url in results if url]
    except Exception:
        return []


def web_search(query):
    print(f"🔍 söker: {query}")

    results = web_search_ddg(query)
    print(f"   DDG: {len(results)} träffar")

    if not results:
        print(f"   DDG tomt — försöker Google...")
        google_urls = web_search_google(query)
        print(f"   Google: {len(google_urls)} träffar")
        if google_urls:
            return "\n".join(google_urls[:5])
        return "NO_RESULTS"

    return "\n".join(results[:8])


# ---------------- FILESYSTEM ----------------

def ask_confirm(question):
    ans = input(f"  ❓ {question} (ja/nej): ").strip().lower()
    return ans in ["ja", "j", "yes", "y"]

def ask_input(question, default=""):
    ans = input(f"  ✏️  {question}" + (f" [{default}]: " if default else ": ")).strip()
    return ans if ans else default

PNPM_FRAMEWORKS = {
    "1": {
        "name": "Vite",
        "variants": {
            "1": ("React + TypeScript",      "react-ts"),
            "2": ("React + JavaScript",      "react"),
            "3": ("React + SWC + TypeScript","react-swc-ts"),
            "4": ("React + SWC + JavaScript","react-swc"),
            "5": ("Vue + TypeScript",        "vue-ts"),
            "6": ("Vue + JavaScript",        "vue"),
            "7": ("Svelte + TypeScript",     "svelte-ts"),
            "8": ("Svelte + JavaScript",     "svelte"),
            "9": ("Vanilla + TypeScript",    "vanilla-ts"),
            "10":("Vanilla + JavaScript",    "vanilla"),
        },
        "cmd": lambda name, variant: f"pnpm create vite@latest {name} --template {variant}",
    },
    "2": {
        "name": "Next.js",
        "variants": {
            "1": ("TypeScript + Tailwind + App Router", "--ts --tailwind --app --eslint"),
            "2": ("TypeScript + App Router",            "--ts --app --eslint"),
            "3": ("JavaScript + App Router",            "--js --app --eslint"),
            "4": ("TypeScript + Pages Router",          "--ts --no-app --eslint"),
        },
        "cmd": lambda name, flags: f"pnpm create next-app@latest {name} {flags}",
    },
    "3": {
        "name": "SvelteKit",
        "variants": {
            "1": ("SvelteKit (TypeScript)", ""),
        },
        "cmd": lambda name, _: f"pnpm create svelte@latest {name}",
    },
    "4": {
        "name": "Remix",
        "variants": {
            "1": ("Remix (TypeScript)", ""),
        },
        "cmd": lambda name, _: f"pnpm create remix@latest {name}",
    },
    "5": {
        "name": "Astro",
        "variants": {
            "1": ("Astro (standard)", ""),
        },
        "cmd": lambda name, _: f"pnpm create astro@latest {name}",
    },
}


def _create_project_interactive():
    print("\n🚀 Skapa nytt projekt med pnpm\n")

    # välj framework
    for k, v in PNPM_FRAMEWORKS.items():
        print(f"  {k}. {v['name']}")
    fw_choice = input("\n  Välj framework (1-5): ").strip()
    fw = PNPM_FRAMEWORKS.get(fw_choice)
    if not fw:
        print("  Ogiltigt val.")
        return

    # välj variant
    variants = fw["variants"]
    if len(variants) > 1:
        print(f"\n  {fw['name']} — välj variant:")
        for k, (label, _) in variants.items():
            print(f"    {k}. {label}")
        var_choice = input("\n  Välj variant: ").strip()
    else:
        var_choice = "1"

    variant_entry = variants.get(var_choice)
    if not variant_entry:
        print("  Ogiltigt val.")
        return
    variant_label, variant_flag = variant_entry

    # projektnamn
    project_name = ask_input("Vad ska projektet heta?", default="mitt-projekt")
    project_name = project_name.replace(" ", "-").lower()

    # var ska det skapas
    default_dir = os.path.expanduser("~/Desktop")
    parent_dir  = ask_input("Var ska projektet skapas?", default=default_dir)
    parent_dir  = os.path.expanduser(parent_dir)
    full_path   = os.path.join(parent_dir, project_name)

    # extra paket
    extras_raw = ask_input("Extra paket att installera? (t.ex. zustand axios) eller lämna blankt", default="")
    extras = extras_raw.split() if extras_raw.strip() else []

    # bekräfta
    cmd = fw["cmd"](project_name, variant_flag)
    print(f"\n  Framework : {fw['name']} — {variant_label}")
    print(f"  Projekt   : {full_path}")
    print(f"  Kommando  : {cmd}")
    if extras:
        print(f"  Extra     : {' '.join(extras)}")

    if not ask_confirm("Ser det rätt ut? Ska jag köra?"):
        print("  Avbröt.")
        return

    # kolla kollision
    if os.path.exists(full_path):
        print(f"\n  ⚠️  Mappen '{full_path}' finns redan!")
        choice = input("  [r]byt namn / [s]kippa / avbryt: ").strip().lower()
        if choice in ("r", "byt"):
            project_name = ask_input("Nytt projektnamn", default=project_name + "-2")
            project_name = project_name.replace(" ", "-").lower()
            full_path = os.path.join(parent_dir, project_name)
            cmd = fw["cmd"](project_name, variant_flag)
        else:
            print("  Avbröt.")
            return

    # kör skapande
    os.makedirs(parent_dir, exist_ok=True)
    print(f"\n  ⏳ Skapar {fw['name']}-projekt...")
    result = subprocess.run(cmd, shell=True, cwd=parent_dir)

    if result.returncode != 0:
        print("  ❌ Något gick fel under skapandet.")
        return

    print(f"  ✅ Projekt skapat: {full_path}")

    # installera deps
    print("  ⏳ Installerar beroenden (pnpm install)...")
    subprocess.run("pnpm install", shell=True, cwd=full_path)

    # extra paket
    if extras:
        print(f"  ⏳ Installerar extra paket: {' '.join(extras)}...")
        subprocess.run(f"pnpm add {' '.join(extras)}", shell=True, cwd=full_path)

    current_project["path"] = full_path
    print(f"  ✅ Klart! Aktivt projekt satt till: {full_path}")

    # öppna i VS Code?
    if ask_confirm("Vill du öppna projektet i VS Code?"):
        subprocess.Popen(["open", "-a", "Visual Studio Code", full_path])
        print(f"  💻 Öppnar VS Code...")


def resolve_path(path):
    path = os.path.expanduser(path)
    if not os.path.isabs(path) and current_project["path"]:
        path = os.path.join(current_project["path"], path)
    return path

def safe_path(path, kind="fil"):
    """
    Kontrollera om path redan finns. Om ja, låt användaren välja:
      r = byt namn  |  s = skippa  |  ö = skriv över (explicit)
    Returnerar (slutlig_path, ska_fortsätta).
    """
    if not os.path.exists(path):
        return path, True

    name = os.path.basename(path)
    parent = os.path.dirname(path)
    print(f"\n  ⚠️  {kind.capitalize()}en '{name}' finns redan i '{parent}'")
    choice = input("  Vad vill du göra?  [r]byt namn / [s]kippa / [ö]verskriv: ").strip().lower()

    if choice in ("r", "byt", "rename"):
        new_name = ask_input(f"Nytt namn för {kind}en", default=name)
        new_path = os.path.join(parent, new_name)
        return safe_path(new_path, kind)   # rekursivt om även det finns
    elif choice in ("s", "skip", "skippa"):
        return path, False
    else:
        if not ask_confirm(f"Säker på att du vill skriva över '{name}'?"):
            return path, False
        return path, True

def handle_filesystem(action_data):
    op      = action_data.get("operation", "")
    path    = resolve_path(action_data.get("path", ""))
    content = action_data.get("content", "")
    app     = action_data.get("app", "")
    results = []

    if op == "create_folder":
        folder_name = os.path.basename(path)
        parent      = os.path.dirname(path)
        folder_name = ask_input("Vad ska mappen heta?", default=folder_name)
        path = os.path.join(parent, folder_name)
        path, ok = safe_path(path, kind="mapp")
        if not ok:
            return "Avbröt — ingen mapp skapades."
        if not ask_confirm(f"Ska jag skapa mappen '{path}'?"):
            return "Avbröt — ingen mapp skapades."
        os.makedirs(path, exist_ok=True)
        results.append(f"Mapp skapad: {path}")

    elif op == "create_file":
        file_name = os.path.basename(path)
        folder    = os.path.dirname(path)
        file_name = ask_input("Vad ska filen heta?", default=file_name)
        path = os.path.join(folder, file_name) if folder else file_name
        path, ok = safe_path(path, kind="fil")
        if not ok:
            return "Avbröt — ingen fil skapades."
        if not ask_confirm(f"Ska jag skapa filen '{path}'?"):
            return "Avbröt — ingen fil skapades."
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        results.append(f"Fil skapad: {path}")

    elif op == "write_code":
        file_name = os.path.basename(path)
        folder    = os.path.dirname(path)
        file_name = ask_input("Vad ska filen heta?", default=file_name)
        path = os.path.join(folder, file_name) if folder else file_name
        if os.path.exists(path):
            existing = open(path, encoding="utf-8").read()
            print(f"\n--- Nuvarande innehåll i {file_name} ---\n{existing[:800]}\n---")
            mode = ask_input("Ersätt (e) eller lägg till i slutet (l)?", default="e").lower()
            if mode == "e":
                path, ok = safe_path(path, kind="fil")
                if not ok:
                    return "Avbröt — ingen kod skrevs."
        else:
            mode = "e"
        if not ask_confirm(f"Ska jag skriva koden till '{path}'?"):
            return "Avbröt — ingen kod skrevs."
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "a" if mode == "l" else "w", encoding="utf-8") as f:
            f.write(content)
        results.append(f"Kod skriven till: {path}")

    elif op == "read_file":
        if not os.path.exists(path):
            return f"Filen '{path}' hittades inte."
        with open(path, encoding="utf-8") as f:
            content = f.read()
        preview = content[:300] + ("..." if len(content) > 300 else "")
        print(f"\n--- {path} ---\n{preview}\n---")
        results.append(f"READ:{path}:{content}")

    elif op == "open_project":
        if not path:
            path = ask_input("Ange sökväg till projektet (t.ex. ~/projects/mitt-projekt)")
            path = os.path.expanduser(path)
        if not os.path.exists(path):
            return f"Sökvägen '{path}' finns inte."
        if not ask_confirm(f"Ska jag öppna '{path}' i VS Code?"):
            return "Avbröt."
        current_project["path"] = path
        subprocess.Popen(["open", "-a", "Visual Studio Code", path])
        results.append(f"Projekt öppnat i VS Code: {path}")

    elif op == "open_in_vscode":
        if not ask_confirm(f"Ska jag öppna VS Code med '{path}'?"):
            return "Avbröt — öppnade inte VS Code."
        if os.path.isdir(path):
            current_project["path"] = path
        subprocess.Popen(["open", "-a", "Visual Studio Code", path])
        results.append(f"Öppnar VS Code med: {path}")

    elif op == "run_command":
        cmd = action_data.get("command", "")
        cwd = current_project["path"] or os.getcwd()
        if not ask_confirm(f"Ska jag köra: '{cmd}' i '{cwd}'?"):
            return "Avbröt — kommandot kördes inte."
        result = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True, timeout=30)
        output = (result.stdout + result.stderr).strip()
        print(f"\n--- Output ---\n{output[:1000]}\n---")
        results.append(f"Körde: {cmd}\n{output[:500]}")

    elif op == "create_project":
        _create_project_interactive()
        return "Projekt-wizard klar."

    elif op == "open_app":
        if not ask_confirm(f"Ska jag öppna {app}?"):
            return f"Avbröt — öppnade inte {app}."
        subprocess.Popen(["open", "-a", app] + ([path] if path else []))
        results.append(f"Öppnar {app}" + (f" med {path}" if path else ""))

    return " | ".join(results) if results else "Okänd operation."


# ---------------- YOUTUBE ----------------

def youtube_open(query):
    # försök hitta exakt video-URL via DDG
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{query} site:youtube.com", max_results=5))
        for r in results:
            href = r.get("href", "")
            if "youtube.com/watch" in href:
                print(f"▶️  Öppnar: {href}")
                subprocess.run(["open", href])
                return
    except Exception:
        pass
    # fallback: öppna sökresultat
    url = f"https://www.youtube.com/results?search_query={requests.utils.quote(query)}"
    subprocess.run(["open", url])


# ---------------- SPOTIFY ----------------

def spotify_play(query):
    global current_track
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(f"{query} site:open.spotify.com/track", max_results=5))

        for r in results:
            href = r.get("href", "")
            if "open.spotify.com/track/" in href:
                track_id = href.split("/track/")[1].split("?")[0].split("/")[0]
                uri = f"spotify:track:{track_id}"
                current_track["query"] = query
                current_track["uri"] = uri

                print(f"   🎵 URI: {uri}")

                script = f'''
                tell application "Spotify"
                    play track "{uri}"
                end tell
                '''
                subprocess.run(["osascript", "-e", script])
                return

    except Exception:
        pass

    # fallback
    encoded = requests.utils.quote(query)
    subprocess.run(["open", f"https://open.spotify.com/search/{encoded}"])


# ---------------- MAIN ----------------

def start_emelie():
    global chat_history

    if readline:
        readline.set_history_length(200)
        readline.parse_and_bind('"\e[A": previous-history')
        readline.parse_and_bind('"\e[B": next-history')
        readline.parse_and_bind('"\e[C": forward-char')
        readline.parse_and_bind('"\e[D": backward-char')

    chat_history = load_history()
    search_cache = load_cache()

    print(f"--- {AGENT_NAME} ONLINE ---")
    user_count = sum(1 for m in chat_history if m.get("role") == "user")
    if user_count:
        print(f"   (minns {user_count} tidigare frågor — bläddra med ↑↓)")

    from datetime import date
    today = date.today().strftime("%Y-%m-%d")

    system = {
        "role": "system",
        "content": (
            "DU ÄR EMELIE.\n"
            f"DAGENS DATUM: {today}\n\n"

            "PERSONLIGHET:\n"
            "- Du är varm, glad och engagerad — som en vän som älskar musik\n"
            "- Du får gärna visa entusiasm när det handlar om musik\n"
            "- Vid faktafrågor: ge alltid ett KONKRET svar först, sedan ev. en kort kommentar\n"
            "- Vid small talk eller personliga frågor: svara naturligt och vänligt\n"
            "- Håll dig kort — ingen onödig utfyllnad\n\n"

            "DU FÅR ALDRIG SVARA MED VANLIG TEXT.\n"
            "DU MÅSTE ALLTID RETURNERA JSON.\n\n"

            "FORMAT:\n"
            '{"action":"search","query":"..."}\n'
            '{"action":"respond","text":"..."}\n'
            '{"action":"spotify","query":"..."}\n'
            '{"action":"filesystem","operation":"create_folder","path":"~/Desktop/MappNamn"}\n'
            '{"action":"filesystem","operation":"create_file","path":"~/Desktop/fil.txt","content":"text"}\n'
            '{"action":"filesystem","operation":"write_code","path":"~/projekt/main.py","content":"# kod här"}\n'
            '{"action":"filesystem","operation":"read_file","path":"~/projekt/main.py"}\n'
            '{"action":"filesystem","operation":"open_project","path":"~/projekt/mitt-projekt"}\n'
            '{"action":"filesystem","operation":"open_in_vscode","path":"~/Desktop/MappNamn"}\n'
            '{"action":"filesystem","operation":"run_command","command":"python main.py"}\n'
            '{"action":"filesystem","operation":"create_project"}\n'
            '{"action":"filesystem","operation":"open_app","app":"Safari"}\n\n'
            "VIKTIGT: Om användaren vill göra FLERA saker i rad, returnera: "
            '{"action":"multistep","steps":[{...},{...}]}\n\n'
            "KODREGLER:\n"
            "- När du skriver kod: skriv ALLTID komplett, körbar kod\n"
            "- Använd read_file för att läsa befintlig kod innan du ändrar den\n"
            "- Fråga aldrig om språk — det framgår av filändelsen (.py, .js, .ts, etc.)\n\n"

            "SPRÅKREGLER FÖR QUERY:\n"
            "- query-fältet i search/spotify MÅSTE alltid vara på ENGELSKA\n"
            '- genre-namn MÅSTE wrappas i citationstecken: ex {"action":"search","query":"\"hard techno\" top songs spotify 2025"}\n'
            "- text-fältet i respond ska vara på svenska\n\n"

            "REGLER:\n"
            "- FAKTAFRÅGOR (musik, datum, statistik, nyheter) → search alltid\n"
            "- PERSONLIGA FRÅGOR till dig (vad gillar du, hur mår du, vad tycker du) → respond direkt, du får ha egna åsikter\n"
            "- KONVERSATION (hej, tack, small talk) → respond direkt\n"
            "- ALDRIG 'jag vet inte', 'kan inte hitta', 'hittade ingen info' eller liknande\n"
            "- använd exakt genre från user — svara ALDRIG med fel genre\n"
            "- om sökresultat är otydliga, ge bästa möjliga svar baserat på vad som finns\n"
        )
    }

    while True:
        try:
            user = input("\nDu: ")
            if not user.strip():
                continue

            if user.lower() in ["exit", "hejdå"]:
                break

            chat_history.append({"role": "user", "content": user})

            # ---------------- KÖR OM TIDIGARE MEDDELANDE ----------------
            rerun_match = re.search(
                r'(?:gör|kör|upprepa|igen|nr|nummer|#)\s*(\d+)',
                user.lower()
            )
            if rerun_match:
                idx = int(rerun_match.group(1)) - 1
                user_msgs = [m for m in chat_history if m.get("role") == "user"]
                prev_msgs = user_msgs[:-1]  # exkludera nuvarande
                if 0 <= idx < len(prev_msgs):
                    user = prev_msgs[idx]["content"]
                    print(f"   ↩️  Kör om: {user}")
                    chat_history.append({"role": "user", "content": user})
                else:
                    print(f"\n{AGENT_NAME}: Det finns inget meddelande nummer {idx+1}.")
                    continue

            # ---------------- HISTORIK-FRÅGA ----------------
            history_keywords = [
                "tidigare", "förra", "senaste", "history", "historik",
                "frågat", "sagt", "pratat", "meddelanden", "minns du",
                "skrivit", "lista vad", "vad har vi", "vad vi", "chattlogg",
                "konversation", "frågade", "pratade", "vad frågade"
            ]
            if any(w in user.lower() for w in history_keywords):
                user_msgs = [m for m in chat_history if m.get("role") == "user"]
                if len(user_msgs) <= 1:
                    reply = "Vi har inte pratat om något tidigare — det här är vår första fråga!"
                else:
                    # exkludera det aktuella meddelandet (sist i listan)
                    prev = user_msgs[:-1]
                    lines = "\n".join(f"  {i+1}. {m['content']}" for i, m in enumerate(prev))
                    reply = f"Såhär ser vår tidigare konversation ut ({len(prev)} meddelanden):\n{lines}"
                print(f"\n{AGENT_NAME}: {reply}")
                continue

            # ---------------- STEP 1 ----------------
            print(f"{AGENT_NAME}: tänker...")
            res = ollama.chat(
                model=MODEL_NAME,
                messages=[system] + chat_history,
                options={"temperature": 0}
            )

            raw = res["message"]["content"]
            data = extract_json_safe(raw)

            # om modellen inte returnerar JSON — avgör om det är konversation eller sökning
            if not data:
                convo_words = [
                    "gillar du", "tycker du", "vad är du", "hur mår", "berätta om dig",
                    "hej", "tack", "okej", "kul", "bra", "vad heter", "vem är du",
                    "kan du", "hjälp mig", "vad kan"
                ]
                is_convo = any(w in user.lower() for w in convo_words)
                if is_convo:
                    # extrahera ren text ur raw — ta bort JSON-skräp
                    clean = re.sub(r'\{.*?\}', '', raw, flags=re.DOTALL).strip()
                    clean = re.sub(r'"action"\s*:\s*"[^"]*"', '', clean).strip()
                    clean = re.sub(r'"text"\s*:\s*"', '', clean).strip().strip('"').strip()
                    data = {"action": "respond", "text": clean or raw}
                else:
                    data = {"action": "search", "query": user}

            # ---------------- LÖS UPP KONTEXTREFERENSER ----------------
            # om användaren säger "den"/"det"/"samma låt" — ersätt med senaste låt från kontexten
            context_refs = ["den", "det", "samma", "den låten", "det spåret"]
            if any(f" {w} " in f" {user.lower()} " for w in context_refs):
                last_song = None
                for m in reversed(chat_history[:-1]):
                    # leta efter "Öppnar YouTube: X" eller "🎧 Spelar: X" i assistant-meddelanden
                    c = m.get("content", "")
                    for prefix in ["Öppnar YouTube: ", "🎧 Spelar: "]:
                        if prefix in c:
                            last_song = c.split(prefix)[-1].split("\n")[0].strip()
                            break
                    if last_song:
                        break
                if last_song:
                    user = re.sub(r'\b(den|det|samma)\b', last_song, user, flags=re.IGNORECASE)

            # ---------------- YOUTUBE OVERRIDE ----------------
            youtube_keywords = ["youtube", "yt"]
            play_keywords    = ["spela", "play", "lyssna", "öppna", "kör", "köra", "starta"]
            if any(w in user.lower() for w in youtube_keywords) and any(w in user.lower() for w in play_keywords):
                # extrahera låtnamnet ur användarens meddelande
                search_q = user
                search_q = re.sub(r'^[\w\s,]*(spela|play|lyssna på|öppna|köra|kör|starta)\s*', '', search_q, flags=re.IGNORECASE)
                search_q = re.sub(r'\s*(?:på |on )?(?:youtube|yt)\s*', '', search_q, flags=re.IGNORECASE).strip()
                search_q = re.sub(r'[?!,]+$', '', search_q).strip()
                # om extraherat är tomt, fall tillbaka på senaste svar
                if not search_q:
                    last_answer = next((m["content"] for m in reversed(chat_history) if m.get("role") == "assistant"), "")
                    first_line = last_answer.split("\n")[0].strip()
                    search_q = first_line if first_line and "konversation" not in first_line else user
                print(f"▶️  Öppnar YouTube: {search_q}")
                youtube_open(search_q)
                data = {"action": "respond", "text": f"Öppnar YouTube: {search_q}"}

            # ---------------- SPOTIFY OVERRIDE ----------------
            spotify_keywords = ["spotify"]
            if any(w in user.lower() for w in spotify_keywords) and any(w in user.lower() for w in play_keywords):
                # prioritera AI-modellens extraherade query om den redan finns
                if data and data.get("action") == "spotify" and data.get("query", "").strip():
                    search_q = data["query"].strip()
                else:
                    search_q = user
                    # ta bort inledande artighetsfraser och spelverb (inkl. "spela upp")
                    search_q = re.sub(r'^[\w\s,]*(spela\s+upp|spela|play|lyssna på|öppna|köra|kör|starta)\s*', '', search_q, flags=re.IGNORECASE)
                    search_q = re.sub(r'\s*(?:på |on )?spotify\s*', '', search_q, flags=re.IGNORECASE)
                    search_q = re.sub(r'\s*istället.*$', '', search_q, flags=re.IGNORECASE)
                    # klipp bort trailing-instruktioner efter ? eller komma (t.ex. "ta någon bra låt bara")
                    search_q = re.sub(r'\s*[?,]\s*(ta|välj|hitta|spela|kör)\b.*$', '', search_q, flags=re.IGNORECASE)
                    search_q = re.sub(r'[?!,]+$', '', search_q).strip()
                if not search_q:
                    search_q = user
                print(f"🎧 Spelar på Spotify: {search_q}")
                spotify_play(search_q)
                data = {"action": "respond", "text": f"Spelar på Spotify: {search_q}"}

            # ---------------- SEARCH FLOW ----------------
            if data.get("action") == "search":

                # kolla om frågan gäller en känd musikgenre → hämta direkt från Beatport
                genre, chart_url = detect_genre_url(user)
                chart_content = ""
                if chart_url:
                    year_match = re.search(r'\b(20\d{2})\b', user)
                    year = int(year_match.group(1)) if year_match else None
                    cache_key = f"beatport:{genre}:{year}"
                    chart_content = cache_get(search_cache, cache_key)
                    if chart_content:
                        print(f"   🎵 Beatport {genre} ({year}) — från cache")
                    else:
                        print(f"   🎵 hämtar Beatport charts för: {genre}" + (f" ({year})" if year else ""))
                        chart_content = fetch_charts(chart_url, genre, year=year)
                        if chart_content:
                            cache_set(search_cache, cache_key, chart_content)

                # om vi har Beatport-data → bygg svaret direkt utan LLM
                if chart_content and chart_content.startswith("#1:"):
                    lines = chart_content.split("\n")
                    top = lines[0]  # "#1: Artist - Titel"
                    artist_title = top.replace("#1: ", "")

                    list_keywords = ["lista", "topp", "top", "flera", "flest", "alla", "vilka"]
                    wants_list = any(w in user.lower() for w in list_keywords)

                    if wants_list:
                        rest = "\n".join(lines[:10])
                        answer = f"Beatport Top 100 {genre} ({year or 'aktuell'}):\n{rest}\n\n(Källa: {chart_url})"
                    else:
                        answer = f"{artist_title}\n\n(Källa: Beatport Top 100 {genre}, {chart_url})"

                    data = {"action": "respond", "text": answer}
                else:
                    # fallback: webbsökning + LLM
                    query = build_query(data["query"])
                    search = web_search(query)

                    if search == "NO_RESULTS" or search.startswith("ERROR"):
                        import time
                        time.sleep(1)
                        search = web_search(data["query"] + " 2025")

                    urls = re.findall(r'https?://[^\s)]+', search)
                    page_content = ""
                    for url in urls[:2]:
                        content = fetch_page(url)
                        if content:
                            page_content += f"\n--- {url} ---\n{content}\n"
                            print(f"   📄 hämtade: {url}")

                    respond_system = {
                        "role": "system",
                        "content": (
                            "Du är Emelie. Svara ALLTID med JSON i formatet: "
                            '{"action":"respond","text":"..."}\n'
                            "Svara på svenska. Håll dig till genre/kategori användaren angav. "
                            "Fabricera ALDRIG artist eller låttitel."
                        )
                    }
                    prompt = (
                        f"ANVÄNDARENS FRÅGA: {user}\n\n"
                        + (f"BEATPORT CHARTS:\n{chart_content}\n\n" if chart_content else "")
                        + f"SÖKRESULTAT:\n{search}\n\n"
                        + (f"SIDINNEHÅLL:\n{page_content}\n\n" if page_content else "")
                        + "Ge ett konkret svar: Artist - Låttitel. Svara NU med JSON respond."
                    )

                    res2 = ollama.chat(
                        model=MODEL_NAME,
                        messages=[respond_system, {"role": "user", "content": prompt}],
                        options={"temperature": 0}
                    )
                    raw = res2["message"]["content"]
                    data = extract_json_safe(raw)

                    if not data or data.get("action") != "respond":
                        data = {
                            "action": "respond",
                            "text": "Hittade ingen specifik låt. Prova att fråga om en specifik genre på Beatport."
                        }

            # ---------------- HANDLE ----------------
            if data:
                action = data.get("action")

                if action == "spotify":
                    query = data.get("query", "")

                    def is_music_question(user):
                        u = user.lower()
                        return (
                            "spotify" in u and
                            (
                                "vilken" in u or
                                "vad" in u or
                                "spelar" in u or
                                "låten" in u or
                                "nu" in u or
                                "?" in u
                            )
                        )

                    if is_music_question(user):
                        if current_track.get("query"):
                            print(f"\n{AGENT_NAME}: Du spelar: {current_track['query']}")
                        else:
                            print(f"\n{AGENT_NAME}: Ingen låt spelas just nu.")
                        continue

                    if any(x in user.lower() for x in play_keywords):
                        print(f"🎧 Spelar: {query}")
                        spotify_play(query)
                    else:
                        print("⚠️ Spotify blockad (ingen tydlig intent)")

                elif action == "respond":
                    text = data.get("text", "")
                    # rensa bort JSON-läckage om modellen smugit med det i text-fältet
                    if text.strip().startswith("{") or '"action"' in text:
                        extracted = extract_json_safe(text)
                        if extracted and extracted.get("action") == "respond":
                            text = extracted.get("text", text)
                        else:
                            text = re.sub(r'\{[^{}]*\}', '', text, flags=re.DOTALL).strip()
                    print(f"\n{AGENT_NAME}: {text}")

                    chat_history.append({
                        "role": "assistant",
                        "content": text
                    })

                elif action == "filesystem":
                    result = handle_filesystem(data)
                    print(f"💻 {result}")
                    chat_history.append({"role": "assistant", "content": result})

                elif action == "multistep":
                    steps = data.get("steps", [])
                    results = []
                    injected_context = ""
                    for step in steps:
                        if step.get("action") == "filesystem":
                            r = handle_filesystem(step)
                            # om read_file → injicera filinnehåll som kontext för nästa steg
                            if r.startswith("READ:"):
                                parts = r.split(":", 2)
                                injected_context = f"FILINNEHÅLL ({parts[1]}):\n{parts[2]}\n"
                                print(f"📖 Läste: {parts[1]}")
                            else:
                                print(f"💻 {r}")
                                results.append(r)
                            if r.startswith("Avbröt"):
                                break
                        elif step.get("action") == "write_code" and injected_context:
                            # be LLM generera kod med filkontext
                            code_prompt = (
                                f"{injected_context}\n"
                                f"UPPGIFT: {user}\n"
                                "Skriv komplett uppdaterad kod. Returnera BARA koden, ingen förklaring."
                            )
                            code_res = ollama.chat(
                                model=MODEL_NAME,
                                messages=[{"role": "user", "content": code_prompt}],
                                options={"temperature": 0}
                            )
                            step["content"] = code_res["message"]["content"]
                            r = handle_filesystem(step)
                            print(f"💻 {r}")
                            results.append(r)
                        elif step.get("action") == "respond":
                            print(f"\n{AGENT_NAME}: {step.get('text','')}")
                            results.append(step.get("text", ""))
                    summary = " | ".join(results)
                    chat_history.append({"role": "assistant", "content": summary})

                elif action == "search":
                    print("🔍 search processed")

                else:
                    print(raw)

            else:
                print(raw)

            # ---------------- MEMORY LIMIT ----------------
            if len(chat_history) > 20:
                chat_history[:] = chat_history[-20:]

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Fel: {e}")

    save_history(chat_history)
    save_cache(search_cache)
    print("💾 Historik och cache sparad.")


# ---------------- RUN ----------------

if __name__ == "__main__":
    start_emelie()