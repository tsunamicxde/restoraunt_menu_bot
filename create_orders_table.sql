CREATE TABLE IF NOT EXISTS orders (
    id serial PRIMARY KEY,
    user_id BIGINT UNIQUE,
    "order" JSONB DEFAULT '[]'::jsonb,
    cost INT DEFAULT 0,
    datetime TIMESTAMP DEFAULT NOW()
);