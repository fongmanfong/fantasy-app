"""
The Yahoo redraft board, and its reconciliation with the composite dynasty
ranking.

This is a **hand-maintained side table**, not an outside source with a pull
sequence: Yahoo's draft-analysis page is behind a login and renders its table
client-side, so there is no clean scrape. `BOARD` below is pasted from
`basketball.fantasysports.yahoo.com/nba/draftanalysis` (Standard scoring), and
`python -m fantasy.redraft` writes it into `redraft_ranks` and rebuilds the
`v_redraft_vs_dynasty` view. Refreshing the board means editing `BOARD` and
re-running that.

`redraft_rank` is Yahoo's own **Rank** column (their projected season value —
the number that orders a redraft). `avg_pick` is the **All Drafts** ADP, kept
alongside because the two diverge where the market is pricing in risk the
projection is not (Haliburton: Rank 12, ADP 25). `v_redraft_vs_dynasty` joins
the board to `v_composite_rankings` on `player_name_key` — the same
`names.normalize()` key every outside source uses, *not* the `name_key()` SQL
macro, which does not fold first-name nicknames and so silently drops
Edwards / Curry / Boozer.

Nothing here is in `schema.sql`: the table carries no league key, it is not
append-only, and a fresh database simply has no board until this module runs.
`query.keeper_board` raises with the reload command when the view is absent.
"""
from .config import DB_PATH
from .names import normalize

# adp_order | player | All Drafts ADP | Yahoo Rank   — pulled 2026-09-07, top 150 by ADP
BOARD = """
1|Victor Wembanyama|2.0|1
2|Nikola Jokic|3.1|2
3|Luka Doncic|5.4|3
4|Shai Gilgeous-Alexander|7.0|4
5|Cade Cunningham|9.7|5
6|Cooper Flagg|11.1|13
7|Tyrese Maxey|12.5|6
8|Jayson Tatum|13.8|7
9|Scottie Barnes|13.8|15
10|Giannis Antetokounmpo|14.1|9
11|Karl-Anthony Towns|15.0|16
12|Kevin Durant|15.3|14
13|Anthony Edwards|17.7|8
14|Alperen Sengun|17.9|23
15|Jalen Johnson|18.3|10
16|Aaron Nesmith|18.3|199
17|Jamal Murray|18.4|17
18|Kawhi Leonard|19.6|18
19|Chet Holmgren|21.0|19
20|Donovan Mitchell|22.5|11
21|LaMelo Ball|22.6|20
22|Austin Reaves|22.6|24
23|Jalen Brunson|22.7|28
24|Stephen Curry|24.0|25
25|Anthony Davis|25.0|21
26|Tyrese Haliburton|25.3|12
27|Trae Young|26.2|22
28|Amen Thompson|28.5|31
29|Walker Kessler|29.4|26
30|Josh Giddey|29.8|27
31|Jalen Duren|30.9|29
32|Devin Booker|31.7|33
33|Evan Mobley|32.0|32
34|Jaylen Brown|32.4|40
35|Bam Adebayo|33.5|36
36|Deni Avdija|34.5|41
37|Domantas Sabonis|34.7|34
38|Trey Murphy III|35.8|30
39|Paolo Banchero|36.8|54
40|Kon Knueppel|37.3|37
41|James Harden|38.0|35
42|Donovan Clingan|40.2|38
43|LeBron James|41.4|42
44|Lauri Markkanen|43.4|44
45|Jalen Williams|44.8|43
46|AJ Green|45.0|260
47|Derrick White|45.4|39
48|Pascal Siakam|47.4|52
49|Joel Embiid|48.2|48
50|Kyrie Irving|48.8|45
51|Brandon Miller|49.3|46
52|Keyonte George|52.3|47
53|Franz Wagner|53.7|51
54|Jaren Jackson Jr.|54.4|50
55|Desmond Bane|54.8|49
56|Stephon Castle|56.0|70
57|Onyeka Okongwu|56.3|57
58|Darius Garland|58.0|53
59|Matas Buzelis|58.7|83
60|Nickeil Alexander-Walker|59.1|55
61|Alexandre Sarr|60.3|56
62|OG Anunoby|61.3|60
63|Tyler Herro|62.3|58
64|Dyson Daniels|62.6|63
65|Cameron Boozer|62.7|65
66|Julius Randle|63.1|64
67|Luke Kornet|64.7|220
68|Naz Reid|65.5|61
69|VJ Edgecombe|65.8|71
70|Dejounte Murray|66.1|59
71|Brook Lopez|67.3|139
72|Ivica Zubac|67.4|68
73|Michael Porter Jr.|68.8|67
74|Zach Edey|69.9|62
75|Zion Williamson|70.5|72
76|Damian Lillard|71.3|66
77|Ryan Rollins|73.5|69
78|Brandon Ingram|73.9|77
79|Kel'el Ware|75.2|82
80|Rudy Gobert|76.2|78
81|AJ Dybantsa|76.5|86
82|Mikal Bridges|76.8|73
83|Payton Pritchard|76.8|80
84|Jaden McDaniels|77.8|74
85|Jarrett Allen|77.9|76
86|Dylan Harper|78.7|79
87|Al Horford|79.0|248
88|Paul George|79.8|75
89|Adem Bona|79.9|189
90|Aaron Wiggins|80.0|271
91|Derik Queen|80.6|94
92|Caleb Wilson|80.7|81
93|De'Aaron Fox|81.6|84
94|Aday Mara|84.8|209
95|Moussa Diabate|85.0|177
96|Luke Kennard|85.1|255
97|T.J. McConnell|85.7|247
98|Coby White|87.0|85
99|De'Andre Hunter|91.0|236
100|Ja Morant|91.1|89
101|Ausar Thompson|91.6|92
102|Andre Drummond|91.7|241
103|Allen Graves|92.0|250
104|Day'Ron Sharpe|92.1|88
105|Daniel Gafford|92.1|134
106|Darryn Peterson|92.6|93
107|Alex Caruso|92.6|282
108|Norman Powell|94.0|91
109|Nic Claxton|94.7|98
110|Myles Turner|95.4|95
111|Ty Jerome|95.9|87
112|GG Jackson|96.0|233
113|Duncan Robinson|96.3|205
114|Jabari Smith Jr.|96.8|111
115|Josh Hart|97.1|97
116|Miles Bridges|97.9|104
117|Immanuel Quickley|99.0|90
118|Jared McCain|100.0|223
119|Cedric Coward|100.3|108
120|Jay Huff|102.3|165
121|Isaiah Hartenstein|102.6|99
122|Cameron Johnson|102.7|148
123|Mark Williams|102.9|96
124|Rui Hachimura|103.3|195
125|Jaime Jaquez Jr.|104.3|117
126|Neemias Queta|104.6|100
127|Johni Broome|105.5|665
128|Kristaps Porzingis|106.3|105
129|Ayo Dosunmu|107.0|101
130|Klay Thompson|108.1|273
131|Jalen Suggs|108.3|102
132|Kelly Oubre Jr.|108.7|145
133|Jalen Green|109.0|124
134|Draymond Green|109.4|147
135|Isaiah Stewart|109.7|157
136|Darius Acuff Jr.|109.8|116
137|RJ Barrett|109.8|123
138|Ajay Mitchell|109.9|142
139|Wendell Carter Jr.|110.1|103
140|Andrew Wiggins|110.2|109
141|Aaron Gordon|110.4|156
142|CJ McCollum|111.3|115
143|Nikola Vucevic|111.4|174
144|Kyshawn George|112.3|106
145|Bobby Portis|113.0|150
146|Davion Mitchell|113.8|137
147|Anfernee Simons|113.8|181
148|Brandin Podziemski|114.1|107
149|Shaedon Sharpe|114.2|146
150|Cason Wallace|114.2|154
""".strip()

VIEW_NAME = "v_redraft_vs_dynasty"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS redraft_ranks (
    redraft_rank     INTEGER   NOT NULL,   -- Yahoo "Rank" column: projected season value
    player_name      VARCHAR   NOT NULL,
    player_name_key  VARCHAR   NOT NULL,   -- names.normalize(player_name); the join key
    avg_pick         DOUBLE,               -- Yahoo "All Drafts" ADP
    adp_order        INTEGER,              -- board position when sorted by ADP
    source           VARCHAR   DEFAULT 'yahoo_redraft',
    loaded_at        TIMESTAMP DEFAULT now()
);

CREATE OR REPLACE VIEW v_redraft_vs_dynasty AS
SELECT
    coalesce(r.player_name, c.player_name)                     AS player,
    r.redraft_rank,
    c.rank                                                     AS dynasty_rank,
    CASE WHEN r.redraft_rank IS NOT NULL AND c.rank IS NOT NULL
         THEN (r.redraft_rank + c.rank) / 2.0 END              AS blended_rank,
    r.redraft_rank - c.rank                                    AS rank_gap,
    r.avg_pick,
    r.adp_order,
    c.score                                                    AS dynasty_score,
    c.age,
    c.player_key,
    coalesce(r.player_name_key, c.player_name_key)             AS player_name_key
FROM redraft_ranks r
FULL OUTER JOIN v_composite_rankings c USING (player_name_key);

COMMENT ON TABLE redraft_ranks IS
  'Yahoo NBA redraft board, hand-pasted (see fantasy/redraft.py). Not in schema.sql, not append-only, no league key. redraft_rank = Yahoo Rank column; avg_pick = All Drafts ADP.';
COMMENT ON VIEW v_redraft_vs_dynasty IS
  'redraft_ranks full-outer-joined to v_composite_rankings on names.normalize key. blended_rank = mean of redraft_rank and dynasty_rank (low = strong on both). rank_gap = redraft_rank - dynasty_rank: positive => dynasty higher (buy-low), negative => redraft higher (sell-high).';
"""


def _rows():
    for line in BOARD.splitlines():
        adp_order, name, adp, yrank = line.split("|")
        yield int(yrank), name, normalize(name), float(adp), int(adp_order)


def ensure_schema(con) -> None:
    """Create `redraft_ranks` and `v_redraft_vs_dynasty` if they are not there."""
    con.execute(_SCHEMA)


def load(con) -> dict:
    """
    Replace the board with `BOARD`. Needs a writable connection.

    Returns a small summary: how many rows went in and how many matched the
    dynasty composite (an unmatched name is a `names.normalize()` gap worth
    seeing, so it is reported rather than hidden).
    """
    ensure_schema(con)
    con.execute("DELETE FROM redraft_ranks")
    con.executemany(
        "INSERT INTO redraft_ranks "
        "(redraft_rank, player_name, player_name_key, avg_pick, adp_order) "
        "VALUES (?, ?, ?, ?, ?)",
        list(_rows()),
    )
    total = con.execute("SELECT count(*) FROM redraft_ranks").fetchone()[0]
    matched = con.execute(
        "SELECT count(*) FROM redraft_ranks r "
        "JOIN v_composite_rankings c USING (player_name_key)"
    ).fetchone()[0]
    unmatched = [
        r[0] for r in con.execute(
            "SELECT r.player_name FROM redraft_ranks r "
            "LEFT JOIN v_composite_rankings c USING (player_name_key) "
            "WHERE c.player_name_key IS NULL ORDER BY r.redraft_rank"
        ).fetchall()
    ]
    return {"loaded": total, "matched": matched, "unmatched": unmatched}


def run() -> dict:
    """
    Open the database writable, (re)load `BOARD`, return `load`'s summary.

    Raises `RuntimeError` when there is no database yet, so the CLI can turn it
    into a one-line error the same way every other write command does.
    """
    import duckdb

    if not DB_PATH.exists():
        raise RuntimeError(f"No database at {DB_PATH}. Run `fantasy pull` first.")
    con = duckdb.connect(str(DB_PATH))
    try:
        return load(con)
    finally:
        con.close()


def main() -> None:
    out = run()
    print(f"loaded {out['loaded']} rows, {out['matched']} matched to the dynasty composite")
    if out["unmatched"]:
        print("unmatched (normalize gap or genuinely unranked): "
              + ", ".join(out["unmatched"]))


if __name__ == "__main__":
    main()
