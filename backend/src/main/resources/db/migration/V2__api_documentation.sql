-- API documentation (BRD CP-API-06 / CP-API-07): query parameters, request headers and body, response headers,
-- and one response per HTTP status code. Stored as a JSON document on the API it describes, because an API here
-- is a single method + path and its documentation is always read and written as a whole.
ALTER TABLE api_definition ADD COLUMN documentation VARCHAR(200000);
