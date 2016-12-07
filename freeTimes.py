import arrow

def replaceHM(date ,h ,m):
  return date.replace(hour = h, minute = m)

def free_time(startDate, endDate, startTime, endTime, busytime):

  bh = arrow.get(startTime).hour
  bm = arrow.get(startTime).minute
  eh = arrow.get(endTime).hour
  em = arrow.get(endTime).minute

  nowDate = bDate = replaceHM(arrow.get(startDate), bh, bm)
  eDate = replaceHM(arrow.get(endDate), eh, em)

  freetime = []
  for event in busytime:
    event_start = arrow.get(event['start'])
    event_end = arrow.get(event['end'])

    if nowDate < event_start:

      while nowDate < replaceHM(event_start, bh, bm):

        if nowDate < replaceHM(nowDate, eh, em):
          freetime.append(
                    (nowDate.format('YYYY-MM-DD HH:mm'),
                    replaceHM(nowDate,eh, em).format(
                        'YYYY-MM-DD HH:mm'))
                    )

        nowDate = replaceHM(nowDate, bh, bm)
        nowDate = nowDate.replace(days =+ 1)

      # for last one free event
      freetime.append(
                (nowDate.format('YYYY-MM-DD HH:mm'),
                event_start.format('YYYY-MM-DD HH:mm')
                ))

    nowDate = event_end

    #freetime.append(event)

  while nowDate < eDate:
    if nowDate < replaceHM(nowDate, eh, em):
      freetime.append(
                (nowDate.format('YYYY-MM-DD HH:mm'),
                replaceHM(nowDate,eh, em).format(
                    'YYYY-MM-DD HH:mm'))
                )

    nowDate = replaceHM(nowDate, bh, bm)
    nowDate = nowDate.replace(days =+ 1)

  return freetime
