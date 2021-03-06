# coding=utf-8
"""Unit tests for source.py.
"""

__author__ = ['Ryan Barrett <granary@ryanb.org>']

import copy

from granary import facebook
from granary import googleplus
from granary import instagram
from granary import source
from granary.source import Source
from granary import testutil
from granary import twitter
from oauth_dropins.webutil import util

import test_facebook
import test_googleplus


LIKES = [{
    'verb': 'like',
    'author': {'id': 'tag:fake.com:person', 'numeric_id': '5'},
    'object': {'url': 'http://foo/like/5'},
    }, {
    'verb': 'like',
    'author': {'id': 'tag:fake.com:6'},
    'object': {'url': 'http://bar/like/6'},
    },
  ]
ACTIVITY = {
  'id': '1',
  'object': {
    'id': '1',
    'tags': LIKES,
    }
  }
RSVPS = [{
    'id': 'tag:fake.com:246_rsvp_11500',
    'objectType': 'activity',
    'verb': 'rsvp-yes',
    'actor': {'displayName': 'Aaron P', 'id': 'tag:fake.com,2013:11500'},
    'url': 'https://facebook.com/246#11500',
    }, {
    'objectType': 'activity',
    'verb': 'rsvp-no',
    'actor': {'displayName': 'Ryan B'},
    'url': 'https://facebook.com/246',
    }, {
    'id': 'tag:fake.com:246_rsvp_987',
    'objectType': 'activity',
    'verb': 'rsvp-maybe',
    'actor': {'displayName': 'Foo', 'id': 'tag:fake.com,2013:987'},
    'url': 'https://facebook.com/246#987',
    }]
EVENT = {
  'id': 'tag:fake.com:246',
  'objectType': 'event',
  'displayName': 'Homebrew Website Club',
  'url': 'https://facebook.com/246',
}
EVENT_WITH_RSVPS = copy.deepcopy(EVENT)
EVENT_WITH_RSVPS.update({
  'attending': [RSVPS[0]['actor']],
  'notAttending': [RSVPS[1]['actor']],
  'maybeAttending': [RSVPS[2]['actor']],
  })


class FakeSource(Source):
  DOMAIN = 'fake.com'

  def __init__(self, **kwargs):
    pass


class SourceTest(testutil.TestCase):

  def setUp(self):
    super(SourceTest, self).setUp()
    self.source = FakeSource()
    self.mox.StubOutWithMock(self.source, 'get_activities')

  def check_original_post_discovery(self, obj, originals, mentions=None,
                                    **kwargs):
    got = Source.original_post_discovery({'object': obj}, **kwargs)
    self.assertItemsEqual(originals, got[0])
    self.assertItemsEqual(mentions or [], got[1])

  def test_original_post_discovery(self):
    check = self.check_original_post_discovery

    # noop
    obj = {
      'objectType': 'article',
      'displayName': 'article abc',
      'url': 'http://example.com/article-abc',
      'tags': [],
    }
    check(obj, [])

    # attachments and tags become upstreamDuplicates
    check({'tags': [{'url': 'http://a', 'objectType': 'article'},
                    {'url': 'http://b'}],
           'attachments': [{'url': 'http://c', 'objectType': 'mention'}]},
          ['http://a', 'http://b', 'http://c'])

    # non-article objectType
    urls = [{'url': 'http://x.com/y', 'objectType': 'image'}]
    check({'attachment': urls}, [])
    check({'tags': urls}, [])

    # permashortcitations
    check({'content': 'x (not.at end) y (at.the end)'}, ['http://at.the/end'])

    # merge with existing tags
    obj.update({
      'content': 'x http://baz/3 yyyy',
      'attachments': [{'objectType': 'article', 'url': 'http://foo/1'}],
      'tags': [{'objectType': 'article', 'url': 'http://bar/2'}],
    })
    check(obj, ['http://foo/1', 'http://bar/2', 'http://baz/3'])

    # links become upstreamDuplicates
    check({'content': 'asdf http://first ooooh http://second qwert'},
          ['http://first', 'http://second'])
    check({'content': 'x http://existing y',
           'upstreamDuplicates': ['http://existing']},
          ['http://existing'])

    # leading parens used to cause us trouble
    check({'content': 'Foo (http://snarfed.org/xyz)'}, ['http://snarfed.org/xyz'])

    # don't duplicate http and https
    check({'content': 'X http://mention Y https://both Z http://both2',
           'upstreamDuplicates': ['http://upstream', 'http://both', 'https://both2']},
          ['http://upstream', 'https://both', 'https://both2', 'http://mention'])

    # don't duplicate PSCs and PSLs with http and https
    for scheme in 'http', 'https':
      url = scheme + '://foo.com/1'
      check({'content': 'x (foo.com/1)', 'tags': [{'url': url}]}, [url])

    check({'content': 'x (foo.com/1)', 'attachments': [{'url': 'http://foo.com/1'}]},
          ['http://foo.com/1'])
    check({'content': 'x (foo.com/1)', 'tags': [{'url': 'https://foo.com/1'}]},
          ['https://foo.com/1'])

    # exclude ellipsized URLs
    for ellipsis in '...', u'…':
      url = 'foo.com/1' + ellipsis
      check({'content': 'x (%s)' % url,
             'attachments': [{'objectType': 'article', 'url': 'http://' + url}]},
            [])

    # exclude ellipsized PSCs and PSLs
    for separator in '/', ' ':
      for ellipsis in '...', u'…':
        check({'content': 'x (ttk.me%s123%s)' % (separator, ellipsis)}, [])

    # domains param
    obj = {
      'content': 'x http://me/a y',
      'upstreamDuplicates': ['http://me/b'],
      'attachments': [{'url': 'http://me/c'}],
      'tags': [{'url': 'http://me/d'}],
    }
    links = ['http://me/a', 'http://me/b', 'http://me/c', 'http://me/d']
    for domains in [], ['me'], ['foo', 'me']:
      check(obj, links)

    check(obj, [], mentions=links, domains=['notme', 'alsonotme'])

    # utm_* query params
    check({'content': 'asdf http://other/link?utm_source=x&utm_medium=y&a=b qwert',
           'upstreamDuplicates': ['http://or.ig/post?utm_campaign=123']},
          ['http://or.ig/post', 'http://other/link?a=b'])

    # invalid URLs
    check({'upstreamDuplicates': [''],
           'tags': [{'url': 'http://bad]'}]},
          [])

  def test_original_post_discovery_follow_redirects(self):
    self.expect_requests_head('http://other/link',
                              redirected_url='http://other/link/redirected'
                             ).MultipleTimes()
    self.expect_requests_head('http://sho.rt/post',
                              redirected_url='http://or.ig/post/redirected'
                             ).MultipleTimes()
    self.mox.ReplayAll()

    obj = {
      'content': 'asdf http://other/link qwert',
      'upstreamDuplicates': ['http://sho.rt/post'],
    }
    originals = ['http://sho.rt/post', 'http://or.ig/post/redirected']
    mentions = ['http://other/link', 'http://other/link/redirected']

    check = self.check_original_post_discovery
    check(obj, originals + mentions)
    check(obj, originals, mentions=mentions, domains=['or.ig'])
    check(obj, ['http://or.ig/post/redirected', 'http://other/link/redirected'],
          include_redirect_sources=False)

  def test_get_like(self):
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_likes=True).AndReturn([ACTIVITY])
    self.mox.ReplayAll()
    self.assert_equals(LIKES[1], self.source.get_like('author', 'activity', '6'))

  def test_get_like_numeric_id(self):
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_likes=True).AndReturn([ACTIVITY])
    self.mox.ReplayAll()
    self.assert_equals(LIKES[0], self.source.get_like('author', 'activity', '5'))

  def test_get_like_not_found(self):
    activity = copy.deepcopy(ACTIVITY)
    del activity['object']['tags']
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_likes=True).AndReturn([activity])
    self.mox.ReplayAll()
    self.assert_equals(None, self.source.get_like('author', 'activity', '6'))

  def test_get_like_no_activity(self):
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_likes=True).AndReturn([])
    self.mox.ReplayAll()
    self.assert_equals(None, self.source.get_like('author', 'activity', '6'))

  def test_get_share(self):
    activity = copy.deepcopy(ACTIVITY)
    share = activity['object']['tags'][1]
    share['verb'] = 'share'
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_shares=True).AndReturn([activity])
    self.mox.ReplayAll()
    self.assert_equals(share, self.source.get_share('author', 'activity', '6'))

  def test_get_share_not_found(self):
    self.source.get_activities(user_id='author', activity_id='activity',
                               fetch_shares=True).AndReturn([ACTIVITY])
    self.mox.ReplayAll()
    self.assert_equals(None, self.source.get_share('author', 'activity', '6'))

  def test_add_rsvps_to_event(self):
    event = copy.deepcopy(EVENT)
    Source.add_rsvps_to_event(event, [])
    self.assert_equals(EVENT, event)

    Source.add_rsvps_to_event(event, RSVPS)
    self.assert_equals(EVENT_WITH_RSVPS, event)

  def test_get_rsvps_from_event(self):
    self.assert_equals([], Source.get_rsvps_from_event(EVENT))
    self.assert_equals(RSVPS, Source.get_rsvps_from_event(EVENT_WITH_RSVPS))

  def test_get_rsvps_from_event_bad_id(self):
    event = copy.deepcopy(EVENT)
    for id in None, 'not_a_tag_uri':
      event['id'] = id
      self.assert_equals([], Source.get_rsvps_from_event(event))

  def test_base_object_multiple_objects(self):
    like = copy.deepcopy(LIKES[0])
    like['object'] = [like['object'], {'url': 'http://fake.com/second/'}]
    self.assert_equals({'id': 'second', 'url': 'http://fake.com/second/'},
                       self.source.base_object(like))

  def test_content_for_create(self):
    def cfc(base, extra):
      obj = base.copy()
      obj.update(extra)
      return self.source._content_for_create(obj)

    self.assertEqual(None, cfc({}, {}))

    for base in ({'objectType': 'article'},
                 {'inReplyTo': {'url': 'http://not/fake'}},
                 {'objectType': 'comment', 'object': {'url': 'http://not/fake'}}):
      self.assertEqual(None, cfc(base, {}))
      self.assertEqual('c', cfc(base, {'content': ' c '}))
      self.assertEqual('c', cfc(base, {'content': 'c', 'displayName': 'n'}))
      self.assertEqual('s', cfc(base, {'content': 'c', 'displayName': 'n',
                                       'summary': 's'}))

    for base in ({'objectType': 'note'},
                 {'inReplyTo': {'url': 'http://fake.com/post'}},
                 {'objectType': 'comment',
                  'object': {'url': 'http://fake.com/post'}}):
      self.assertEqual(None, cfc(base, {}))
      self.assertEqual('n', cfc(base, {'displayName': 'n'}))
      self.assertEqual('c', cfc(base, {'displayName': 'n', 'content': 'c'}))
      self.assertEqual('s', cfc(base, {'displayName': 'n', 'content': 'c',
                                       'summary': ' s '}))

  def test_activity_changed(self):
    fb_post = test_facebook.ACTIVITY
    fb_post_edited = copy.deepcopy(fb_post)
    fb_post_edited['object']['updated'] = '2016-01-02T00:58:26+00:00'

    fb_comment = test_facebook.COMMENT_OBJS[0]
    fb_comment_edited = copy.deepcopy(fb_comment)
    fb_comment_edited['published'] = '2016-01-02T00:58:26+00:00'

    gp_like = test_googleplus.LIKE
    gp_like_edited = copy.deepcopy(gp_like)
    gp_like_edited['author'] = test_googleplus.RESHARER

    for before, after in (({}, {}),
                          ({'x': 1}, {'y': 2}),
                          ({'to': None}, {'to': ''}),
                          (fb_post, fb_post_edited),
                          (fb_comment, fb_comment_edited),
                          (gp_like, gp_like_edited)):
      self.assertFalse(self.source.activity_changed(before, after, log=True),
                                                    '%s\n%s' % (before, after))

    fb_comment_edited['content'] = 'new content'
    gp_like_edited['to'] = [{'objectType':'group', 'alias':'@private'}]

    fb_invite = test_facebook.RSVP_OBJS_WITH_ID[3]
    self.assertEqual('invite', fb_invite['verb'])
    fb_rsvp = copy.copy(fb_invite)
    fb_rsvp['verb'] = 'rsvp-yes'

    for before, after in ((fb_comment, fb_comment_edited),
                          (gp_like, gp_like_edited),
                          (fb_invite, fb_rsvp)):
      self.assertTrue(self.source.activity_changed(before, after, log=True),
                                                   '%s\n%s' % (before, after))

  def test_sources_global(self):
    self.assertEquals(facebook.Facebook, source.sources['facebook'])
    self.assertEquals(googleplus.GooglePlus, source.sources['google+'])
    self.assertEquals(instagram.Instagram, source.sources['instagram'])
    self.assertEquals(twitter.Twitter, source.sources['twitter'])

  def test_follow_redirects(self):
    for i in range(2):
      self.expect_requests_head('http://will/redirect',
                                redirected_url='http://final/url')
    self.mox.ReplayAll()

    cache = util.CacheDict()
    self.assert_equals(
      'http://final/url',
      source.follow_redirects('http://will/redirect', cache=cache).url)

    self.assertEquals('http://final/url', cache['R http://will/redirect'].url)

    # another call without cache should refetch
    self.assert_equals(
      'http://final/url',
      source.follow_redirects('http://will/redirect').url)

    # another call with cache shouldn't refetch
    self.assert_equals(
      'http://final/url',
      source.follow_redirects('http://will/redirect', cache=cache).url)

  def test_follow_redirects_with_refresh_header(self):
    headers = {'x': 'y'}
    self.expect_requests_head('http://will/redirect', headers=headers,
                              response_headers={'refresh': '0; url=http://refresh'})
    self.expect_requests_head('http://refresh', headers=headers,
                              redirected_url='http://final')

    self.mox.ReplayAll()
    cache = util.CacheDict()
    self.assert_equals('http://final',
                       source.follow_redirects('http://will/redirect', cache=cache,
                                               headers=headers).url)

  def test_follow_redirects_defaults_scheme_to_http(self):
    self.expect_requests_head('http://foo/bar', redirected_url='http://final')
    self.mox.ReplayAll()
    self.assert_equals('http://final', source.follow_redirects('foo/bar').url)
