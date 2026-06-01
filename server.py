from flask import Flask, jsonify, request
import requests
import json
 
app = Flask(__name__)
 
PLAYHQ_URL = "https://api.playhq.com/graphql"
 
PLAYHQ_QUERY = """
query DiscoverGrade($gradeID: ID!) {
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
    "Accept-Encoding": "gzip, deflate, br",
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
}
 
 
def fetch_ladder(grade_id):
    payload = {
        "operationName": "DiscoverGrade",
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
        data = res.json()
    except Exception:
        return jsonify({"error": "PlayHQ returned invalid JSON", "raw": res.text[:500]}), 500
 
    if "errors" in data:
        return jsonify({"error": "GraphQL errors", "details": data["errors"]}), 400
 
    try:
        grade = data["data"]["discoverGrade"]
        standings = grade["ladder"][0]["standings"]
    except (KeyError, IndexError, TypeError) as e:
        return jsonify({"error": f"Unexpected response shape: {e}", "raw": data}), 500
 
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
 
 
@app.route("/health")
def health():
    return jsonify({"status": "ok"})
 
 
if __name__ == "__main__":
    app.run(port=5000, debug=True)
 
