"""Source-bound dialogue speaker edits and read-only layout inspection."""
from .text import cue_joins_sentences,units,unicode_text


LOCALIZED_LABELS = {
    '倫也': 'Tomoya', '恵': 'Megumi', '英梨々': 'Eriri', '詩羽': 'Utaha',
    '美智留': 'Michiru', '伊織': 'Iori', '出海': 'Izumi', '？？？': '???',
    'クラスメイト': 'Bạn cùng lớp', 'クラスメイトＢ': 'Bạn cùng lớp B',
    'みんな': 'Mọi người', '巡璃': 'Meguri', '瑠璃': 'Ruri',
}


def speaker_name(formatter, value):
    return unicode_text(formatter.ordinary(value, geometry_only=True)['name'])


def propose_speaker(formatter, current, original, speaker=None, expected_speaker=None):
    """Build a prefix and, for bare dialogue, an outer quote pair around the raw body."""
    if formatter is None:
        raise ValueError('Load the game text format before editing a speaker')
    source_speaker = speaker_name(formatter, original) if original is not None else ''
    target = LOCALIZED_LABELS.get(source_speaker) if speaker is None else speaker
    if target is None:
        raise ValueError('No established label for this source speaker. Supply the reviewed speaker label explicitly.')
    opening = unicode_text(formatter.following[1])
    closing = unicode_text(formatter.tokens[5][0])
    forbidden = set(unicode_text(formatter.tokens[2]) + opening + closing + '\r\n\0')
    target_units = units(target)
    normalized_target = formatter.normalize(target_units)
    if (not target or target != target.strip() or len(target_units) > 128
            or not normalized_target or formatter.break_char in normalized_target
            or not forbidden.isdisjoint(target)):
        raise ValueError('Speaker must be a plain, single-line label of at most 128 UTF-16 units')

    previous = formatter.ordinary(current)
    visible_name = unicode_text(previous['name'])
    if expected_speaker is not None and visible_name != expected_speaker:
        raise ValueError('Stale expected speaker; re-read the Message')
    visible, separator, hidden = current.partition('\0')
    added_wrapper = False
    if visible_name:
        raw_prefix, mark, tail = visible.partition(opening)
        if not mark or formatter.normalize(units(raw_prefix)) != previous['name'] or not forbidden.isdisjoint(raw_prefix):
            raise ValueError('Speaker prefix uses nonliteral syntax and needs manual review')
        if expected_speaker is None and previous['name'] != normalized_target and visible_name != source_speaker:
            raise ValueError('Message already has a different speaker. Supply its exact visible label as expected_speaker.')
        body = mark + tail
        result = target + body
    elif visible.startswith(opening):
        result = target + visible
    else:
        added_wrapper = True
        result = target + opening + visible + closing
    result += separator + hidden

    parsed = formatter.ordinary(result)
    padding = len(units(opening)) if added_wrapper else 0
    body = units(opening) + previous['body'] + units(closing) if added_wrapper else previous['body']
    if (added_wrapper and previous['body'][:1] in tuple(formatter.following[0][:2])
            and parsed['body'] == previous['body']):
        # Native parenthetical asides suppress the wrapper on screen. Its
        # delimiters are still stored, and the authored content is untouched.
        body=previous['body']
        padding=0
    controls_unchanged = (
        parsed['markers'] == [[at+padding, lane, time] for at, lane, time in previous['markers']]
        and parsed['ruby'] == [[start+padding, end+padding, reading] for start,end,reading in previous['ruby']]
        and parsed['keywords'] == [[start+padding, end+padding, keyword] for start,end,keyword in previous['keywords']]
    )
    if parsed['name'] != normalized_target or parsed['body'] != body or not controls_unchanged:
        raise ValueError('The native parser would change the dialogue body or inline controls for this speaker')
    return dict(text=result, speaker=unicode_text(parsed['name']), previous_speaker=visible_name or None,
                original_speaker=source_speaker or None, added_wrapper=added_wrapper)


def queue_cues(parsed):
    body=parsed['body']
    result=[]
    for index,lane,time in parsed['markers']:
        result.append(dict(body_index=index,lane=lane,time_ms=time,
                           joined_sentence_boundary=cue_joins_sentences(body,index)))
    return result


def message_inspection(project, font, settings, script_id, command, value, side=0, regions=None):
    from .textcleanup import dialogue_capacity
    from .textlayout import TextLayoutService

    service = TextLayoutService(font, settings, project=project, script_id=script_id,
                                command=command, regions=regions)
    mode = service.resolve_mode('auto')
    visible = value.partition('\0')[0]
    if mode == 'battle':
        recipe = dict(family='battle', state=dict(view=1, font_authored=command.font_authored,
                      **{f'bubble_{1-side}': 3, f'dialogue_{side}': visible}))
    else:
        plate = command.args['speaker']
        recipe = dict(family='message', state=dict(speaker=plate if 0 <= plate <= 8 else -1, text=visible,
                      font_authored=command.font_authored))
    context_required = bool(command.args.get('selector') or command.args.get('completion'))
    try:
        packet = service.measure_dialogue(visible, dialogue_mode=mode,font_authored=command.font_authored)
        capacity = (packet.get('region') or {}).get('capacity') or dialogue_capacity(font, settings, mode)
        fits = (packet['line_count'] <= capacity and max(packet['visible_line_widths'], default=0) <= packet['width']
                and not packet['ruby_overflow'])
        layout = {key: packet[key] for key in ('line_widths', 'visible_line_widths', 'line_count', 'width', 'ruby_overflow', 'timed_markers')}
        layout.update(capacity=capacity, standalone_fits=fits, context_required=context_required)
    except (ValueError, KeyError, OSError) as error:
        layout = dict(standalone_fits=None, context_required=context_required, warning=str(error))
    return recipe, layout
