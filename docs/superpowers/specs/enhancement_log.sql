CREATE TABLE foto.enhancement_log (
    nim VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL,
    error_message TEXT,
    processed_at TIMESTAMP DEFAULT now()
);
