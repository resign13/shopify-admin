# New-order voice reminders

Delivery is off by default. Order INSERT collection remains active when delivery is off.
Existing authentication remains single-login; use independent staff accounts on different computers.
Admin/warehouse use their order view scope; sales only receive `owner_admin_id` matches.

## Local validation

Run the fixed, approved read-only database sync at `D:/dulizhan/shopify-admin/scripts/sync-production-db.py` before development.
Manual servers use the active feature worktree and `127.0.0.1:55439/lumiere_admin`, real synced accounts, unchanged passwords.
Set `ORDER_VOICE_ENABLED=1` and a private random `ORDER_VOICE_CURSOR_SECRET` of at least 32 bytes in the ignored local backend `.env`.
Automated fixtures must explicitly use a local `*_test` database; no fixture writes to the mirror.

Audio is a fixed WAV generated with Windows Microsoft Huihui Desktop: 您有新的外贸部订单，请注意查收。
Every clip contains exactly two identical copies of the phrase, separated by 500 ms of silence.
Normal delivery plays one complete clip per order, so each order is announced twice without overlapping audio.
Only completion of both phrases marks the event processed. An interrupted clip remains subject to manual verification.
Reconnect summaries retain the merged-batch rule and play one complete double-phrase clip for the batch.
Enable/test playback uses the same clip. Rebuild it on Windows with `scripts/generate-order-voice.ps1 -Python <python.exe>`.
There is no runtime TTS, desktop agent or Bluetooth device control. Windows chooses the output device.
Click enable/test before expecting audio. Refresh retains progress but requires sound activation.
Only an activated tab can become Web Locks leader. Pending, playing, uncertain and completed items are stored atomically in IndexedDB.
An interrupted playing item requires manual replay; playback completion is not a physical speaker acknowledgement.

## Backend protocol

All routes are authenticated POSTs under `/api/admin/order-notifications`, authorized through the orders view module.
`start`: `{requestId: UUID}` -> enabled, cursor, serverTime. Retries preserve the baseline per login session.
`poll`: `{cursor, recovery?: boolean}` -> enabled, events, cursor, serverTime, hasMore, recovery, recoveryComplete, cutoffAt.
`validate`: `{cursor, eventIds: number[]}` -> enabled, valid events, serverTime. Maximum 100 IDs.
Events contain only eventId, orderId, orderNo and createdAt (database recording time, ISO UTC).
Scan at most 100 events before ownership filtering. The signed cursor carries a fixed recovery end and cutoff across pages.
Signed cursors expire after seven days without successful polling and are invalid in another login or enable period.
401/403 stop the episode; 409 requires a new baseline; disabled delivery returns enabled=false.

## Maintenance and retention

Historical imports must use a dedicated connection with `SET gingtto.notifications_paused='on'`, or
`ORDER_NOTIFICATION_MAINTENANCE=1` for the importing process. Do not apply this environment flag globally in production.
The local sync pauses collection only during local staging restore/migration and verifies fingerprints before session cleanup.
It does not change the production read-only encrypted export channel or the daily 04:00 automation.
Schema migrations are additive and identical in both backends. No history backfill and no counter reset.
The systemd timer removes only expired events at 03:00 Beijing time daily. Publication progress is retained.

## Release / rollback

No deployment is performed by local development. Publish compatible backend migrations/APIs first with delivery off,
then the admin UI. Existing GitHub Actions remains the deployment mechanism.
Configure the private signing secret outside Git, test on the actual Windows/Chrome/Edge/Bluetooth setup, then explicitly enable delivery.
On failure disable delivery first. Keep notification tables/triggers and existing signed-stock/defect/ownership compatibility when rolling back.

## Acceptance still requiring a person

Verify audible output on the intended Bluetooth speaker, foreground empty-queue announcement within ten seconds,
sequential bursts, reconnect summary, tab takeover and at least one working day of minimized/background behavior.
Do not apply foreground latency criteria to frozen/discarded browser pages.
