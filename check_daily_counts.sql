-- Run on the DuckLake/DuckDB connection in DBeaver.
-- Assumes created_at stores UTC timestamps.
SELECT
    DATE(CONVERT_TZ(
        ao.created_at, '+00:00', '+05:45'
    )) AS nepal_date,
    COUNT(*) AS cnt
FROM automation_operations AS ao
LEFT JOIN merchants AS m
    ON ao.merchant_id = m.id
WHERE ao.currency = 'NPR'
    AND LOWER(TRIM(ao.sender_email)) NOT IN (
        'test1123@gmail.com',
        'bottesting12@gmail.com',
        'testacc1@gmail.com'
    )
    AND m.code NOT IN ('S0001', 'TEST0001', 'SYS0001')
GROUP BY 1
ORDER BY 1 DESC;
