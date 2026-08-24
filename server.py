from flask import Flask, jsonify, request
import requests
import json
from bs4 import BeautifulSoup

app = Flask(__name__)

PLAYHQ_URL = "https://api.playhq.com/graphql"

PLAYHQ_QUERY = """
query gradeLadder($gradeID: ID!) {
  discoverGrade(gradeID: $gradeID) {
    id
    name
    ladder {
      standings {
        team { name }
        played
        won
        lost
        drawn
        byes
        pointsFor
        pointsAgainst
        percentage
        competitionPoints
      }
    }
  }
}
"""

# These headers closely mimic what a real browser sends to PlayHQ
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-AU,en-GB;q=0.9,en;q=0.8",
    "Content-Type": "application/json",
    "Origin": "https://www.playhq.com",
    "Referer": "https://www.playhq.com/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-site",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
    "Connection": "keep-alive",
    "tenant": "afl",
}


def fetch_ladder(grade_id):
    payload = {
        "operationName": "gradeLadder",
        "query": PLAYHQ_QUERY,
        "variables": {"gradeID": grade_id},
    }
    res = requests.post(
        PLAYHQ_URL,
        headers=HEADERS,
        json=payload,
        timeout=15,
    )
    return res


def extract_standings(data, grade_id):
    """Try multiple response shapes to extract standings."""
    # Shape 1: data.discoverGrade.ladder[0].standings (original)
    try:
        grade = data["data"]["discoverGrade"]
        ladder = grade.get("ladder")
        if ladder:
            # ladder can be a list or dict
            if isinstance(ladder, list) and len(ladder) > 0:
                return grade, ladder[0]["standings"]
            elif isinstance(ladder, dict):
                return grade, ladder.get("standings", [])
    except (KeyError, TypeError, IndexError):
        pass

    # Shape 2: data.grade.ladder
    try:
        grade = data["data"]["grade"]
        ladder = grade.get("ladder")
        if ladder:
            if isinstance(ladder, list) and len(ladder) > 0:
                return grade, ladder[0]["standings"]
            elif isinstance(ladder, dict):
                return grade, ladder.get("standings", [])
    except (KeyError, TypeError, IndexError):
        pass

    return None, None


@app.route("/ladder")
def ladder():
    grade_id = request.args.get("id")
    if not grade_id:
        return jsonify({"error": "Missing ?id= parameter"}), 400

    try:
        res = fetch_ladder(grade_id)
    except requests.exceptions.Timeout:
        return jsonify({"error": "PlayHQ request timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if res.status_code != 200:
        return jsonify({
            "error": "PlayHQ returned non-200",
            "status": res.status_code,
            "body": res.text[:500],
        }), res.status_code

    try:
        # requests automatically decompresses gzip/brotli when we call .json()
        data = res.json()
    except Exception:
        return jsonify({
            "error": "PlayHQ returned invalid JSON",
            "raw": res.content[:200].hex()  # show hex for debugging
        }), 500

    if "errors" in data:
        return jsonify({"error": "GraphQL errors", "details": data["errors"]}), 400

    grade, standings = extract_standings(data, grade_id)
    if grade is None or standings is None:
        # Log full response for debugging
        return jsonify({
            "error": "Could not extract standings from response",
            "keys": list(data.get("data", {}).keys()),
            "raw_sample": str(data)[:500]
        }), 500

    result = []
    for i, s in enumerate(standings):
        result.append({
            "position": i + 1,
            "team": s["team"]["name"],
            "played": s["played"],
            "won": s["won"],
            "lost": s["lost"],
            "drawn": s["drawn"],
            "byes": s["byes"],
            "for": s["pointsFor"],
            "against": s["pointsAgainst"],
            "percentage": s["percentage"],
            "points": s["competitionPoints"],
        })

    return jsonify({
        "grade": grade["name"],
        "standings": result,
    })



WAFL_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}


@app.route("/wafl")
def wafl():
    try:
        res = requests.get(
            "https://www.wafl.com.au/ladders",
            headers=WAFL_HEADERS,
            timeout=15,
        )
    except requests.exceptions.Timeout:
        return jsonify({"error": "WAFL request timed out"}), 504
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if res.status_code != 200:
        return jsonify({"error": f"WAFL returned {res.status_code}"}), res.status_code

    try:
        soup = BeautifulSoup(res.text, "html.parser")

        # Find the ladder table — it's the main table on the page
        table = soup.find("table")
        if not table:
            return jsonify({"error": "No table found on WAFL page"}), 500

        standings = []
        rows = table.find("tbody").find_all("tr") if table.find("tbody") else table.find_all("tr")

        for i, row in enumerate(rows):
            cells = row.find_all(["td", "th"])
            if len(cells) < 8:
                continue

            # Extract text from each cell, strip whitespace
            vals = [c.get_text(strip=True) for c in cells]

            # Table columns: Club, C(bye), P, W, L, D, F, A, %, PTS, FORM
            # Club name is in first cell — may include img alt text so get just text
            team_name = cells[0].get_text(strip=True)
            # Remove any trailing form letters that got merged
            if not team_name:
                continue

            try:
                standings.append({
                    "position": i + 1,
                    "team": team_name,
                    "played": int(vals[2]) if vals[2].isdigit() else 0,
                    "won":    int(vals[3]) if vals[3].isdigit() else 0,
                    "lost":   int(vals[4]) if vals[4].isdigit() else 0,
                    "drawn":  int(vals[5]) if vals[5].isdigit() else 0,
                    "for":    int(vals[6]) if vals[6].isdigit() else 0,
                    "against":int(vals[7]) if vals[7].isdigit() else 0,
                    "percentage": float(vals[8].replace("%","")) if vals[8] else 0,
                    "points": int(vals[9]) if len(vals) > 9 and vals[9].isdigit() else 0,
                })
            except (ValueError, IndexError):
                continue

        if not standings:
            return jsonify({"error": "Could not parse any teams from WAFL table"}), 500

        return jsonify({
            "grade": "WAFL League 2026",
            "standings": standings,
        })

    except Exception as e:
        return jsonify({"error": f"Parse error: {str(e)}"}), 500

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(port=5000, debug=True)
