-- Payin amount
-- Engine: PostgreSQL, orders + users/user_parents hierarchy (trader -> team lead -> head team -> agent)

WITH h AS (
    SELECT
        child_user_id,
        MAX(CASE WHEN as_role = 'teamlead' THEN parent_user_id END) AS tl_id,
        MAX(CASE WHEN as_role = 'headteam' THEN parent_user_id END) AS htl_id,
        MAX(CASE WHEN as_role = 'agent'    THEN parent_user_id END) AS agent_id
    FROM user_parents
    GROUP BY child_user_id
),
base AS (
    SELECT
        o.amount,
        o.status,
        o.user_id,
        o.payment_type,
        o.bank,
        u.name  AS trader_name,
        tl.name AS tl_name,
        ht.name AS htl_name,
        ag.name AS agent_name
    FROM orders o
    JOIN merchants m  ON m.id = o.merchant_id AND m.actual = true
    LEFT JOIN users u  ON u.id = o.user_id
    LEFT JOIN h        ON h.child_user_id = o.user_id
    LEFT JOIN users tl ON tl.id = h.tl_id
    LEFT JOIN users ht ON ht.id = h.htl_id
    LEFT JOIN users ag ON ag.id = h.agent_id
    WHERE o.type = 'deposit'
      AND o.created_at::date BETWEEN
          CASE
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN split_part({{period}}, '~', 1)::date
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN {{period}}::date
              WHEN {{period}} ~ '^past[0-9]+days$'
                  THEN current_date - regexp_replace({{period}}, '[^0-9]', '', 'g')::int
              WHEN {{period}} = 'thisweek'
                  THEN date_trunc('week', current_date)::date
              WHEN {{period}} = 'thismonth'
                  THEN date_trunc('month', current_date)::date
              WHEN {{period}} = 'lastweek'
                  THEN date_trunc('week', current_date - 7)::date
              WHEN {{period}} = 'lastmonth'
                  THEN date_trunc('month', current_date - 32)::date
              ELSE current_date
          END
          AND
          CASE
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}~[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN split_part({{period}}, '~', 2)::date
              WHEN {{period}} ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
                  THEN {{period}}::date
              WHEN {{period}} = 'lastweek'
                  THEN (date_trunc('week', current_date) - interval '1 day')::date
              WHEN {{period}} = 'lastmonth'
                  THEN (date_trunc('month', current_date) - interval '1 day')::date
              ELSE current_date
          END
      [[AND o.payment_type = {{method}}]]
      [[AND o.bank = {{bank}}]]
      [[AND o.amount >= {{amount_from}}::numeric]]
      [[AND o.amount <= {{amount_to}}::numeric]]
      [[AND u.name = {{trader}}]]
      [[AND tl.name = {{tla}}]]
      [[AND ht.name = {{htl}}]]
      [[AND ag.name = {{agent}}]]
)
SELECT round(COALESCE(sum(amount), 0)::numeric, 2) AS "Сумма заявок" FROM base
