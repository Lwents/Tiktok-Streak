"""Conservative streak evidence from TikTok system notices plus complete daily exchanges.

This reports a lower bound from message history, never TikTok's current counter.
No user message text is needed or stored.
"""
from datetime import date, timedelta

RESTORE_SCENES = {
    'streak_new_recover', 'streak_new_recover_with_pet',
    'streak_new_recover_no_pet', 'streak_new_recover_with_pet_few_restore_left',
}
POSITIVE_SCENES = RESTORE_SCENES | {
    'streak_interaction_unlock', 'streak_milestone_upgrade',
}
GROUP_RESTORE_SCENES = {'streak_group_recover'}
GROUP_POSITIVE_SCENES = GROUP_RESTORE_SCENES | {'streak_group_unlock', 'streak_group_upgrade'}
RESTORABLE_END_SCENES = {'streak_end_with_restore', 'streak_end_with_restore_with_pet',
                         'streak_group_end_with_restore', 'streak_group_end_with_restore_with_pet'}
# User-sent message kinds in the web SDK; system notices and bot responses are excluded.
USER_TYPES = {2, 3, 4, 5, 6, 7, 8, 11, 15, 16, 19, 21, 22, 25, 26, 33, 40, 43, 71, 72, 81, 101,
              1021, 1025, 1033, 1034, 1036, 1038, 1039, 1801, 1802, 1803, 1805, 1806, 1809,
              1811, 1813, 10001, 10002, 10003, 10004, 10005, 10006, 10007, 10009, 10011}


def analyze_history(snapshot):
    today = date.fromisoformat(snapshot['today'])
    now = snapshot['checked_at']
    days = {}
    positives, endings = [], []
    seen = set()
    is_group = snapshot.get('is_group', False)
    self_today, peer_today = False, False
    for message in snapshot.get('messages', []):
        message_id = message.get('id')
        if not message_id or message_id in seen:
            continue
        seen.add(message_id)
        timestamp = message.get('at', 0)
        if not isinstance(timestamp, (int, float)) or timestamp <= 0 or timestamp > now + 300:
            continue
        try:
            day = date.fromisoformat(message['day'])
        except (ValueError, KeyError):
            continue
        if day > today:
            continue
        scene = message.get('scene', '')
        if message.get('type') == 1 and message.get('valid', True):
            if scene in (GROUP_POSITIVE_SCENES if is_group else POSITIVE_SCENES):
                positives.append((timestamp, day, scene))
            elif scene.startswith(('streak_end', 'streak_group_end')):
                endings.append((timestamp, day, scene, message_id))
        direction = message.get('direction')
        if message.get('type') in USER_TYPES and direction in ('self', 'peer') and message.get('valid', False):
            sender = message.get('sender_id', '') if is_group else direction
            if is_group and (not isinstance(sender, str) or not sender.isdecimal() or int(sender) <= 0):
                continue
            days.setdefault(day, set()).add(sender)
            if day == today:
                self_today |= direction == 'self'
                peer_today |= direction == 'peer'
    # A group can exchange messages between two other members while we are away.
    exchanged = lambda day: len(days.get(day, set())) >= 2
    both_today = exchanged(today)
    anchor = today if both_today else today - timedelta(days=1)
    current = anchor
    run = []
    while exchanged(current):
        run.append(current)
        current -= timedelta(days=1)
    result = {'status': 'unknown', 'days_lower_bound': len(run),
              'self_sent_today': self_today,
              'peer_sent_today': peer_today,
              'is_group': is_group,
              'timezone': snapshot.get('timezone', ''), 'checked_at': now,
              'anchor_day': anchor.isoformat(),
              'last_exchange_day': anchor.isoformat() if run else None}
    # An explicit ending is meaningful even when the missing daily exchange
    # makes every older positive notice ineligible for the active streak.
    if endings:
        ended_at, ended_day, end_scene, event_id = max(endings)
        if ended_at >= max((p[0] for p in positives), default=0):
            offered = end_scene in RESTORABLE_END_SCENES
            deadline = ended_at + 48 * 3600
            result.update(reason='later_end_notice', recovery={
                'status': 'available' if offered and now < deadline else 'expired' if offered else 'unavailable',
                'event_id': event_id, 'ended_at': ended_at, 'ended_day': ended_day.isoformat(),
                'deadline_at': deadline, 'scene': end_scene})
            return result
    # A genuine TikTok notice establishes the streak on its own day. A restore
    # deliberately repairs missing exchanges before/on that day: requiring three
    # new mutual days would hide restored streaks, including a restore today.
    # Every completed day AFTER the notice must still have mutual exchanges.
    first_supported = current
    eligible = [p for p in positives if first_supported <= p[1] <= today]
    if not eligible:
        result['reason'] = ('insufficient_daily_exchange' if len(run) < 3
                            else 'no_tiktok_system_confirmation')
        return result
    timestamp, marker_day, scene = max(eligible)
    if any(ending[0] >= timestamp for ending in endings):
        result['reason'] = 'later_end_notice'
        return result
    result.update(status='history_confirmed', reason='system_notice_and_daily_exchange',
                  days_lower_bound=max(3, len(run)),
                  observed_exchange_days=len(run),
                  restored=scene in RESTORE_SCENES | GROUP_RESTORE_SCENES,
                  marker_scene=scene, marker_day=marker_day.isoformat(), marker_at=timestamp,
                  exchange_days=[day.isoformat() for day in reversed(run)])
    return result


def analyze_reply(snapshot):
    """Only a successful user message from this account satisfies today's reply.

    A negative answer requires reaching yesterday or the end of server history;
    a short cache/page with no self message is not proof that none exists.
    """
    today = date.fromisoformat(snapshot['today'])
    now = snapshot['checked_at']
    result = {'status': 'unknown', 'day': today.isoformat(), 'checked_at': now,
              'timezone': snapshot.get('timezone', '')}
    ends_at = snapshot.get('day_ends_at')
    if isinstance(ends_at, (int, float)) and now < ends_at <= now + 27 * 3600:
        result['valid_until'] = ends_at
    sent = []
    reached_yesterday = False
    seen = set()
    for message in snapshot.get('messages', []):
        identity, at = message.get('id'), message.get('at', 0)
        if not identity or identity == '0' or identity in seen:
            continue
        seen.add(identity)
        if not isinstance(at, (int, float)) or at <= 0 or at > now + 300:
            continue
        try:
            day = date.fromisoformat(message['day'])
        except (ValueError, KeyError):
            continue
        reached_yesterday |= day < today
        if (day == today and message.get('valid', False) and message.get('type') in USER_TYPES
                and message.get('direction') == 'self'):
            sent.append(at)
    if sent:
        result.update(status='replied', sent_at=max(sent))
    elif reached_yesterday or snapshot.get('has_more') is False:
        result['status'] = 'needed'
    return result
