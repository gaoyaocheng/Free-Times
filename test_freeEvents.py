from freeEvents import *

def test_none_event():
    res = free_events("2016-11-19","2016-11-19","2016-11-19T08:00:00:00", "2016-11-19T17:00:00:00", [])
    assert len(res) == 1
    res = free_events("2016-11-17","2016-11-19","2016-11-17T08:00:00:00", "2016-11-19T17:00:00:00", [])
    assert len(res) == 3

def test_single_event():
  busyevents = [{'summary': 'test', 'start': "2016-11-17T08:00:00:00", 'end': "2016-11-17T08:30:00:00"}]

  events = free_events("2016-11-17","2016-11-17","2016-11-17T08:00:00:00", "2016-11-17T17:00:00:00", busyevents)
  assert events == [{'end': '2016-11-17T08:30:00:00', 'start': '2016-11-17T08:00:00:00', 'summary': 'test'},                     {'end': '2016-11-17 17:00', 'summary': 'Free', 'start': '2016-11-17 08:30'}]

def test_multiple_events():
  busyevents = [{'summary': 'test1', 'start': "2016-11-17T08:00:00:00", 'end': "2016-11-17T08:30:00:00"},
                {'summary': 'test2', 'start': "2016-11-17T13:21:00:00", 'end': "2016-11-17T15:55:00:00"}]
  events = free_events("2016-11-17","2016-11-17","2016-11-17T08:00:00:00", "2016-11-17T17:00:00:00",
          busyevents)
  assert events == [{'summary': 'test1', 'end': '2016-11-17T08:30:00:00', 'start': '2016-11-17T08:00:00:00'},                    {'summary': 'Free', 'end': '2016-11-17 13:21', 'start': '2016-11-17 08:30'},
                    {'summary': 'test2', 'end': '2016-11-17T15:55:00:00', 'start': '2016-11-17T13:21:00:00'},                    {'summary': 'Free', 'end': '2016-11-17 17:00', 'start': '2016-11-17 15:55'}]

