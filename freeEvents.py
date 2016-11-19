import arrow

def replaceHM(date ,h ,m):
  return date.replace(hour = h, minute = m)

def free_events(startDate, endDate, startTime, endTime, busyEvents):

  bh = arrow.get(startTime).hour
  bm = arrow.get(startTime).minute
  eh = arrow.get(endTime).hour
  em = arrow.get(endTime).minute

  nowDate = bDate = replaceHM(arrow.get(startDate), bh, bm)
  eDate = replaceHM(arrow.get(endDate), eh, em)

  freeEvents= []
  for event in busyEvents:
    event_start = arrow.get(event['start'])
    event_end = arrow.get(event['end'])

    if nowDate < event_start:

      while nowDate < replaceHM(event_start, bh, bm):

        if nowDate < replaceHM(nowDate, eh, em):
          freeEvents.append({
                    'start': nowDate.format('YYYY-MM-DD HH:mm'),
                    'end': replaceHM(nowDate,eh, em).format(
                        'YYYY-MM-DD HH:mm'),
                    'summary': 'Free'
                    })

        nowDate = replaceHM(nowDate, bh, bm)
        nowDate = nowDate.replace(days =+ 1)

      # for last one free event
      freeEvents.append({
                'start': nowDate.format('YYYY-MM-DD HH:mm'),
                'end': event_start.format('YYYY-MM-DD HH:mm'),
                'summary': 'Free'
                })

    nowDate = event_end

    freeEvents.append(event)

  while nowDate < eDate:
    if nowDate < replaceHM(nowDate, eh, em):
      freeEvents.append({
                'start': nowDate.format('YYYY-MM-DD HH:mm'),
                'end': replaceHM(nowDate,eh, em).format(
                    'YYYY-MM-DD HH:mm'),
                'summary': 'Free'
                })

    nowDate = replaceHM(nowDate, bh, bm)
    nowDate = nowDate.replace(days =+ 1)

  return freeEvents
