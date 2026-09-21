SELECT
    m.code AS merchant_code,
    ao.merchant_order_id,
    ao.transaction_type,
    ao.bank_name,
    ao.amount,
    ao.created_at,
    ao.end_time,
    ao.status,
    ao.remark,
    ao.error_message,
    ao.sender_name, 
    ao.sender_email,
    ao.sender_account_number,
    ao.created_at + INTERVAL '5 hours 45 minutes' AS converted_created_at,
    ao.end_time + INTERVAL '5 hours 45 minutes' AS converted_end_time,
    -- Duration in seconds; NULL when either timestamp is missing.
    date_diff('second', ao.created_at, ao.end_time) AS duration,
    CASE
        WHEN UPPER(TRIM(m.code)) IN (
            'NPR1PAY', 'N511A3X01', 'K9WIN-NPR', 'N605A1J15',
            'N605A5T30', 'HIMAWIN', 'JILI8848', 'SULIFU7777',
            'XEPAY', 'NPWIN365', '911PAY', '1WIN',
            '1ST GAME', 'HIMALAYA', 'OZWIN365', 'TM555'
        ) THEN 'ASH'
        WHEN UPPER(TRIM(m.code)) IN ('MW99', 'HW99') THEN 'BEAR'
        WHEN UPPER(TRIM(m.code)) IN ('FW8', 'OKWIN178') THEN 'BLACK'
        WHEN UPPER(TRIM(m.code)) = 'VIJAY8' THEN 'EDISON'
        WHEN UPPER(TRIM(m.code)) = 'JUWA8' THEN 'LDH'
        WHEN UPPER(TRIM(m.code)) IN (
            'ULTRAPAY', 'NP321', 'KTM77', 'NP96',
            'IME77', 'NEPAL8', 'HIMA8', 'JEERAJ',
            'ROYALNEPA', 'NEPALWIN', '95NP', 'DSTGAMING',
            'KYASINO88', 'KTM', 'NB8', 'PAYPRO', 'TAB66',
            '1HIMA', '8KUBER','NK101'
        ) THEN 'TIGER'
        WHEN UPPER(TRIM(m.code)) = 'TKASH' THEN 'TKASH'
        WHEN UPPER(TRIM(m.code)) IN (
            'BOUNCINGBALL8NPR', 'DD99', 'GOLDPAYNPR',
            'GLOBALPAY', 'WOLF777', 'SECURE8'
        ) THEN 'WILSON'
        WHEN UPPER(TRIM(m.code)) IN (
            'A8N', 'B8N', 'DH8N', 'I8N',
            'J1N', 'J8N', 'JB8N', 'K33N',
            'K8N', 'M8N', 'N88N', 'N9N',
            'R8N', 'Y7N'
        ) THEN 'INTERNAL'
        WHEN UPPER(TRIM(m.code)) IN ('8MBETS', 'MG33', 'NPL11') THEN 'NONE'
        ELSE 'UNASSIGNED'
    END AS agent,
    CASE
        WHEN m.email NOT IN (
            'karman@wetop.asia',
            'ts@neratech.co',
            'fa1@wetop.asia'
        ) THEN 'External'
        ELSE 'Internal'
    END AS merchant_category
FROM ducklake.ingest_ntpay.automation_operations AS ao
LEFT JOIN ducklake.ingest_ntpay.merchants AS m
    ON ao.merchant_id = m.id
WHERE ao.currency = 'NPR'
    AND (
        ao.sender_email IS NULL
        OR LOWER(TRIM(ao.sender_email)) NOT IN (
            -- 'luck1234@gmail.com',
            -- 'ming123@gmail.com',
            'test1123@gmail.com',
            -- 'oreo5833@gmail.com',
            'bottesting12@gmail.com',
            'testacc1@gmail.com'
            -- 'winwin01@gmail.com',
            -- 'oreo5897@gmail.com',
            -- 'imking666@gmail.com'
        )
    ) and merchant_code not in ('S0001', 'TEST0001', 'SYS0001')
order by ao.created_at desc;
