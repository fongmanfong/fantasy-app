from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, JSON, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class League(Base):
    __tablename__ = "leagues"

    id = Column(Integer, primary_key=True, autoincrement=True)
    yahoo_league_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    season = Column(Integer)
    num_teams = Column(Integer)
    current_week = Column(Integer)
    scoring_type = Column(String)  # headhead, headhead_each_category, roto, pickem
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    settings = relationship("LeagueSettings", back_populates="league", uselist=False, cascade="all, delete-orphan")
    teams = relationship("Team", back_populates="league", cascade="all, delete-orphan")
    matchups = relationship("Matchup", back_populates="league", cascade="all, delete-orphan")
    sync_logs = relationship("SyncLog", back_populates="league", cascade="all, delete-orphan")


class LeagueSettings(Base):
    __tablename__ = "league_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), unique=True, nullable=False)
    # Stat categories as JSON: [{"name": "PTS", "display": "Points", "is_only_display": false}, ...]
    stat_categories = Column(JSON, default=list)
    # For points leagues: {"PTS": 1.0, "REB": 1.2, ...}
    stat_weights = Column(JSON, default=dict)
    # Roster positions: {"PG": 1, "SG": 1, "SF": 1, "PF": 1, "C": 1, "G": 1, "F": 1, "UTIL": 1, "BN": 3, "IL": 2}
    roster_positions = Column(JSON, default=dict)
    max_teams = Column(Integer)
    waiver_type = Column(String)
    trade_deadline = Column(String)
    playoff_start_week = Column(Integer)
    playoff_end_week = Column(Integer)
    raw_settings = Column(JSON, default=dict)  # full raw settings from Yahoo

    league = relationship("League", back_populates="settings")


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    yahoo_team_id = Column(String, nullable=False)
    name = Column(String, nullable=False)
    manager_name = Column(String)
    is_my_team = Column(Boolean, default=False)
    wins = Column(Integer, default=0)
    losses = Column(Integer, default=0)
    ties = Column(Integer, default=0)
    points_for = Column(Float, default=0.0)
    points_against = Column(Float, default=0.0)
    standing = Column(Integer)
    waiver_priority = Column(Integer)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("league_id", "yahoo_team_id"),)

    league = relationship("League", back_populates="teams")
    roster = relationship("Roster", back_populates="team", cascade="all, delete-orphan")
    home_matchups = relationship("Matchup", foreign_keys="Matchup.home_team_id", back_populates="home_team")
    away_matchups = relationship("Matchup", foreign_keys="Matchup.away_team_id", back_populates="away_team")


class Player(Base):
    __tablename__ = "players"

    id = Column(Integer, primary_key=True, autoincrement=True)
    yahoo_player_id = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    nba_team = Column(String)
    positions = Column(JSON, default=list)  # ["PG", "SG"]
    injury_status = Column(String)  # "Healthy", "GTD", "O", "IR", etc.
    image_url = Column(String)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    stats = relationship("PlayerStats", back_populates="player", cascade="all, delete-orphan")
    news = relationship("PlayerNews", back_populates="player", cascade="all, delete-orphan")
    roster_entries = relationship("Roster", back_populates="player")


class PlayerStats(Base):
    __tablename__ = "player_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    stat_period = Column(String, nullable=False)  # "season", "last_7", "last_14", "last_30", "week_N"
    games_played = Column(Integer, default=0)
    games_this_week = Column(Integer, default=0)  # scheduled games remaining this week
    stats = Column(JSON, default=dict)  # {"PTS": 22.1, "REB": 5.3, ...}
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("player_id", "league_id", "stat_period"),)

    player = relationship("Player", back_populates="stats")


class Roster(Base):
    __tablename__ = "rosters"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    roster_position = Column(String)  # actual slot: "PG", "BN", "IL", etc.
    is_free_agent = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("team_id", "player_id"),)

    team = relationship("Team", back_populates="roster")
    player = relationship("Player", back_populates="roster_entries")


class Matchup(Base):
    __tablename__ = "matchups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=False)
    week = Column(Integer, nullable=False)
    home_team_id = Column(Integer, ForeignKey("teams.id"))
    away_team_id = Column(Integer, ForeignKey("teams.id"))
    home_stats = Column(JSON, default=dict)   # {"PTS": 110.2, ...}
    away_stats = Column(JSON, default=dict)
    home_score = Column(Float)  # for points leagues
    away_score = Column(Float)
    # category results for H2H cat leagues: {"PTS": "home", "REB": "away", ...}
    category_results = Column(JSON, default=dict)
    is_current = Column(Boolean, default=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (UniqueConstraint("league_id", "week", "home_team_id", "away_team_id"),)

    league = relationship("League", back_populates="matchups")
    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="home_matchups")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="away_matchups")


class PlayerNews(Base):
    __tablename__ = "player_news"

    id = Column(Integer, primary_key=True, autoincrement=True)
    player_id = Column(Integer, ForeignKey("players.id"), nullable=False)
    source = Column(String)
    headline = Column(String)
    body = Column(Text)
    published_at = Column(DateTime)
    scraped_at = Column(DateTime, default=datetime.utcnow)

    player = relationship("Player", back_populates="news")


class YahooCredentials(Base):
    __tablename__ = "yahoo_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, nullable=False)
    client_secret = Column(String, nullable=False)
    access_token = Column(Text)
    refresh_token = Column(Text)
    token_expires_at = Column(DateTime)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SyncLog(Base):
    __tablename__ = "sync_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    league_id = Column(Integer, ForeignKey("leagues.id"), nullable=True)
    sync_type = Column(String)  # "full", "roster", "stats", "news", "matchup"
    status = Column(String)     # "success", "error", "running"
    message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    league = relationship("League", back_populates="sync_logs")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, unique=True, nullable=False)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
