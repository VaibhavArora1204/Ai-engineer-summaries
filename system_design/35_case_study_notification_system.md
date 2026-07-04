# 35 — Case Study: Notification System

## Requirements Clarification

**Functional:**
- Send notifications across multiple channels: push (mobile), email, SMS, in-app.
- A single event (e.g., "Order shipped") triggers notifications on one or more channels based on user preferences.
- Priority levels: critical (payment failed), normal (order shipped), low (marketing).
- Rate limiting per user per channel to prevent notification spam.

**Non-Functional:**
- Handle 200M users, 3 notifications per user per day = 600M notifications/day.
- Peak QPS: 35,000 notifications/second (flash sale announcements).
- Deduplication: never send the same notification twice.
- Delivery within: critical < 30 seconds, normal < 5 minutes, low < 1 hour.

---

## Back-of-Envelope Estimation

```
Volume: 600M notifications/day.
QPS: 600M / 86,400 ≈ 7,000/second average.
Peak: 5x → 35,000/second.

External API calls (push, email, SMS):
  35,000/second to external providers at peak.
  Each provider has its own rate limits:
    - Firebase Cloud Messaging (FCM): ~500K/second capacity (generous)
    - Email (SendGrid): ~100K/hour on standard plan
    - SMS (Twilio): ~100 messages/second (expensive, slow)
  
  SMS is the bottleneck. 35K/sec would require dedicated short codes and custom routing.

Storage:
  Each notification record: 200 bytes.
  600M/day × 200 bytes = 120 GB/day.
  Retention: 90 days → 10.8 TB.
```

---

## High-Level Design

```
Event Source → Event Bus (Kafka) → Notification Service
                                        ↓
                                  ┌──────┼──────┐
                                  ↓      ↓      ↓
                               Priority  Fan-out  Preference
                               Queue     Engine   Service
                                  ↓
                         Channel Queues
                    ┌────────┼────────┐
                    ↓        ↓        ↓
                Push Queue  Email    SMS Queue
                    ↓       Queue       ↓
                FCM API     ↓       Twilio API
                         SendGrid
```

### The Request Flow

1. **Event arrives:** "Order #456 shipped" event published to Kafka by the Order Service.
2. **Notification Service consumes the event.** Looks up user preferences: "User wants push + email for shipping updates."
3. **Deduplication check:** Has notification `order_shipped:456:user:789` already been sent? Check Redis dedup set. If yes, skip.
4. **Fan-out:** Create two notification tasks: one for push, one for email.
5. **Priority queuing:** Push notification goes to the high-priority push queue. Marketing emails go to the low-priority email queue.
6. **Channel workers:** Dedicated workers consume from each channel queue and call the external provider API (FCM for push, SendGrid for email, Twilio for SMS).
7. **Record delivery:** Write to the notification database: what was sent, when, which channel, delivery status.

---

## Deep Dive: The Genuinely Hard Parts

### 1. Fan-Out From a Single Event

One event → multiple notifications → multiple channels.

```python
async def process_event(event):
    user_id = event['user_id']
    
    # Get user preferences
    preferences = await get_user_preferences(user_id)
    # preferences = {"push": True, "email": True, "sms": False}
    
    notification = {
        "id": generate_id(),
        "user_id": user_id,
        "event_type": event['type'],
        "title": "Your order has shipped!",
        "body": f"Order #{event['order_id']} is on its way.",
        "data": event['data']
    }
    
    # Fan-out to channel-specific queues
    if preferences.get('push'):
        await push_queue.publish(notification)
    if preferences.get('email'):
        await email_queue.publish({**notification, "email": user['email']})
    if preferences.get('sms'):
        await sms_queue.publish({**notification, "phone": user['phone']})
```

### 2. Deduplication (Callback to Module 24)

Events can be delivered more than once (Kafka at-least-once). Without dedup, a user gets 3 copies of "Your order shipped!"

```python
dedup_key = f"notif:{event['type']}:{event['entity_id']}:{user_id}"
if await redis.setnx(dedup_key, 1):
    redis.expire(dedup_key, 86400)  # 24-hour dedup window
    await process_notification(event)
else:
    log.info(f"Duplicate notification suppressed: {dedup_key}")
```

### 3. Priority Queues

Critical notifications (payment failed, account compromised) must skip ahead of millions of queued marketing emails.

**Implementation:** Separate queues per priority level with dedicated workers.

```
critical_queue → 10 workers (always running, instant processing)
normal_queue   → 50 workers (steady throughput)
low_queue      → 20 workers (throttled, batch processing)
```

Workers for the critical queue are always available. Workers for the low-priority queue are throttled to avoid overwhelming email providers during peak.

### 4. Rate Limiting Per User Per Channel

A user should not receive more than 5 push notifications per hour (regardless of how many events fire). Marketing emails should be limited to 1 per day.

```python
async def can_send(user_id, channel, notification_type):
    key = f"rate:{user_id}:{channel}:{notification_type}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, RATE_LIMIT_WINDOWS[notification_type])
    
    return count <= RATE_LIMITS[(channel, notification_type)]
    # e.g., RATE_LIMITS[("push", "marketing")] = 5 per hour
```

### 5. Handling External Provider Failures

External providers (FCM, SendGrid, Twilio) have their own rate limits, occasional outages, and variable latency.

**Pattern:** Circuit breaker (Module 18) per provider:
```python
@circuit_breaker(failure_threshold=5, reset_timeout=60)
async def send_push(notification):
    response = await fcm.send(notification)
    if response.status == 429:  # Rate limited by FCM
        raise RateLimitError()
    return response
```

If FCM returns 5 consecutive errors, the circuit opens and push notifications are buffered in the queue until FCM recovers. This prevents hammering a failing provider and gives the queue backpressure time to absorb the burst.

**Retry with exponential backoff:**
Failed notifications go to a retry queue with delays: 1 minute → 5 minutes → 30 minutes → 2 hours → give up → Dead Letter Queue.

---

## The Tradeoffs

| Decision | Benefit | Cost |
|---------|---------|------|
| Separate queues per channel | Independent scaling, isolated failures | More infrastructure to manage |
| Priority queues | Critical notifications bypass marketing queue | Complexity of priority management |
| Per-user rate limiting | Prevents notification spam | Redis memory for rate limit counters |
| Deduplication in Redis | Prevents duplicate sends | 24-hour dedup window consumes memory |
| Async processing via queues | API returns instantly, notifications processed in background | User doesn't see notification for seconds/minutes |

---

## Mentor's Take — What Actually Matters Here

**What matters:** The fan-out pattern (one event → multiple channels), deduplication (never send twice), and priority queuing (critical beats marketing). These three concepts apply to every notification system from a startup's first push notification to Google-scale alerts.

The external provider management (rate limits, retries, circuit breakers) is the operationally hardest part. Each provider (FCM, APNS, SendGrid, Twilio) has its own quirks, rate limits, authentication patterns, and failure modes. In practice, you spend more time handling provider edge cases than designing the notification system itself.

**The AI-era connection:** Agent-triggered notifications are a new wrinkle. In a traditional system, notifications are triggered by deterministic events: "order shipped" → send notification. The trigger is rules-based. You know exactly when and why a notification fires.

In an agent system, the agent DECIDES to notify the user based on its reasoning: "I found an important update about your portfolio — I should alert the user." This introduces:
- **Non-deterministic triggers:** The agent might decide to send 20 notifications in a day or zero. Rate limiting per user becomes critical.
- **Content quality risk:** The agent might generate misleading notification content. You need guardrails (content moderation, template-based notifications where the agent fills in variables but doesn't write the full text).
- **Cost tracking:** Each agent-decided notification involves an LLM call to generate the content. Runaway agent notification loops (agent keeps deciding things are important) could consume significant LLM budget.

**Brutally honest advice:** Start with email only. Add push notifications when your mobile app has enough users to justify the FCM/APNS integration effort. Add SMS only for security-critical notifications (2FA codes, fraud alerts). SMS costs $0.01-$0.05 per message — at 600M notifications/day, SMS costs $6M-$30M/month. Nobody at startup scale needs SMS for marketing. Don't over-build notification infrastructure before you have notification-worthy content to send.

---

## Check Your Understanding

1. A flash sale starts. Your system needs to send 10 million push notifications in 5 minutes. FCM handles 500K messages/second, which is sufficient. But your notification workers are currently processing 3 million queued marketing emails. How do priority queues prevent the marketing emails from delaying the flash sale notifications?

2. A Kafka consumer processes an "order shipped" event and sends a push notification. The consumer crashes before committing its Kafka offset. Kafka re-delivers the event. Without deduplication, what happens? With the Redis-based dedup key, what happens?

3. An AI agent monitoring a user's stock portfolio decides to send 15 push notifications in 1 hour ("AAPL up 2%", "GOOGL down 1%", etc.). The user has set their preference to max 3 notifications per hour. Describe the interaction between the agent's decision and the rate limiter.

4. Your email provider (SendGrid) goes down for 20 minutes. During this time, 500,000 emails queue up. When SendGrid recovers, what happens if you release all 500,000 at once? How should you handle the recovery?

5. Explain why notification delivery is eventually consistent by design and why this is acceptable.

---

### Answers

1. **Answer:** Flash sale notifications go to the `critical_queue` (or `high_priority_queue`). Marketing emails are in the `low_priority_queue`. These are separate queues with separate worker pools. The 10 critical queue workers immediately start sending push notifications to FCM at full speed. The marketing email workers continue processing at their own pace in their own queue. The two workloads don't compete for the same workers or queue capacity. The flash sale notifications are sent within minutes regardless of the marketing email backlog.

2. **Answer:** Without dedup: the consumer processes the event again, sends a second push notification. The user receives "Your order has shipped!" twice. With Redis dedup: the consumer attempts `SETNX` on the key `notif:order_shipped:456:user:789`. Redis returns False (key already exists from the first processing). The consumer logs "duplicate suppressed" and skips the notification. The user receives exactly one notification.

3. **Answer:** The agent generates 15 notification intents. Each intent passes through the rate limiter: `can_send(user_id, "push", "portfolio_update")`. The first 3 pass (counter: 1, 2, 3). The 4th through 15th are rejected by the rate limiter (counter > 3). The rate limiter returns `False`, and the notification service silently drops them (or aggregates them: "You have 12 more portfolio updates — tap to view"). The agent's decision is overridden by the user's preference. This is a critical safety mechanism for agent-triggered notifications.

4. **Answer:** Releasing 500,000 emails at once would: (1) Overwhelm SendGrid's rate limits (they might throttle or block you). (2) Cause a spike in email delivery that might trigger spam filters (ISPs flag sudden bursts as spam). (3) Overload your own email workers. Recovery pattern: ramp up gradually. Start at 10% of normal throughput. If delivery succeeds, increase to 25%, 50%, 100% over 15-30 minutes. This gradual ramp respects provider rate limits and avoids spam classification.

5. **Answer:** Notification delivery is eventually consistent because the notification is processed asynchronously after the triggering event. There's a delay between "order shipped" and the user receiving the push notification (seconds to minutes). This is acceptable because: (1) The notification is informational, not transactional — the order is shipped regardless of whether the notification arrives. (2) Users don't expect instant push notifications — a 5-second delay is imperceptible. (3) The alternative (synchronous notification in the order-shipping request path) would block the order process if the push provider is slow, degrading the critical path for a non-critical feature.
