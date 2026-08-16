-- Enable PostGIS extension
CREATE EXTENSION IF NOT EXISTS postgis;

-- Users table
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'member',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Default admin user  (password: admin  — change in production!)
-- Hash generated with: passlib.hash.bcrypt.hash('admin')
INSERT INTO users (username, hashed_password, role)
VALUES ('admin', '$2b$12$EixZaYVK1fsbw1ZfbX3OXePaWxn96p36WQoeG6Lruj3vjPGga31lW', 'admin')
ON CONFLICT (username) DO NOTHING;

-- Drones table
CREATE TABLE IF NOT EXISTS drones (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    altitude DOUBLE PRECISION DEFAULT 0.0,
    battery_level DOUBLE PRECISION DEFAULT 100.0,
    is_active BOOLEAN DEFAULT FALSE,
    feed_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drone configs table (stores launch parameters for stop/resume)
CREATE TABLE IF NOT EXISTS drone_configs (
    drone_id   VARCHAR(50) PRIMARY KEY,
    drone_name VARCHAR(100) NOT NULL,
    source     TEXT NOT NULL,
    latitude   DOUBLE PRECISION NOT NULL,
    longitude  DOUBLE PRECISION NOT NULL,
    altitude   DOUBLE PRECISION DEFAULT 100.0,
    zone       VARCHAR(200) DEFAULT 'Live Stream Zone',
    fps        INTEGER DEFAULT 5,
    loop       BOOLEAN DEFAULT FALSE,
    model      VARCHAR(50) DEFAULT 'sdnet',
    device     VARCHAR(50) DEFAULT 'cpu',
    status     VARCHAR(20) DEFAULT 'stopped',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Density records table
CREATE TABLE IF NOT EXISTS density_records (
    id SERIAL PRIMARY KEY,
    drone_id VARCHAR(50) REFERENCES drones(id),
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    person_count INTEGER DEFAULT 0,
    density_level DOUBLE PRECISION DEFAULT 0.0,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Spatial index on density records
CREATE INDEX IF NOT EXISTS idx_density_location
    ON density_records USING GIST (
        ST_MakePoint(longitude, latitude)
    );

-- Index on timestamp for time-range queries
CREATE INDEX IF NOT EXISTS idx_density_timestamp
    ON density_records (timestamp DESC);

-- Composite index for per-drone time-range queries
CREATE INDEX IF NOT EXISTS idx_density_drone_timestamp
    ON density_records (drone_id, timestamp DESC);
