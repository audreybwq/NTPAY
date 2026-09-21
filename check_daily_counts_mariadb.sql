-- Execute this entire script in the source MariaDB connection in DBeaver.
SELECT DATABASE() AS source_database, @@session.time_zone AS original_session_timezone;
SHOW COLUMNS FROM automation_operations LIKE 'created_at';

-- Assumes created_at is returned as UTC; does not change the session timezone.

SELECT
    DATE(CONVERT_TZ(ao.created_at, '+00:00', '+05:45')) AS nepal_date,
    ao.transaction_type,
    COUNT(*) AS cnt,
    MIN(ao.created_at) AS first_created_at_utc,
    MAX(ao.created_at) AS last_created_at_utc
FROM automation_operations AS ao
LEFT JOIN merchants AS m ON ao.merchant_id = m.id
WHERE ao.currency = 'NPR'
AND (
    ao.sender_email IS NULL
    OR LOWER(TRIM(ao.sender_email)) NOT IN (
        'test1123@gmail.com',
        'bottesting12@gmail.com',
        'testacc1@gmail.com'
    )
)
  AND m.code NOT IN ('S0001', 'TEST0001', 'SYS0001')
GROUP BY 1, 2
ORDER BY 1 DESC, 2;
