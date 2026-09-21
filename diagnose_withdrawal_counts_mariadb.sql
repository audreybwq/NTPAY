-- Run in MariaDB. Each NPR operation is assigned exactly one filter outcome.
-- EXISTS avoids multiplying operations if merchant rows are duplicated.
SELECT transaction_type, filter_outcome, COUNT(*) AS cnt
FROM (
    SELECT ao.transaction_type,
        CASE
            WHEN NOT EXISTS (
                SELECT 1 FROM backoffice_prod.merchants m
                WHERE m.id = ao.merchant_id
                  AND m.code NOT IN ('S0001', 'TEST0001', 'SYS0001')
            ) THEN '1_excluded_by_merchant'
            WHEN ao.sender_email IS NULL THEN '2_excluded_null_sender_email'
            WHEN LOWER(TRIM(ao.sender_email)) IN (
                'test1123@gmail.com', 'bottesting12@gmail.com', 'testacc1@gmail.com'
            ) THEN '3_excluded_test_email'
            ELSE '4_included_by_current_filters'
        END AS filter_outcome
    FROM backoffice_prod.automation_operations ao
    WHERE ao.currency = 'NPR'
) diagnostic
GROUP BY transaction_type, filter_outcome
ORDER BY transaction_type, filter_outcome;
