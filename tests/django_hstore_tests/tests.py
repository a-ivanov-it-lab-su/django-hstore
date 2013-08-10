from .models import DataBag, Ref, RefsBag, DefaultsModel, BadDefaultsModel, Location

from django.db import transaction
from django.db.models.aggregates import Count
from django.db.utils import IntegrityError
from django.utils.unittest import TestCase
from django.contrib.gis.geos import GEOSGeometry
import json


class TestDictionaryField(TestCase):
    def setUp(self):
        DataBag.objects.all().delete()
        Ref.objects.all().delete()
        RefsBag.objects.all().delete()
        Location.objects.all().delete()
        
    pnt1 = GEOSGeometry('POINT(65.5758316 57.1345383)')
    pnt2 = GEOSGeometry('POINT(65.2316 57.3423233)')

    def _create_bags(self):
        alpha = DataBag.objects.create(name='alpha', data={'v': '1', 'v2': '3'})
        beta = DataBag.objects.create(name='beta', data={'v': '2', 'v2': '4'})
        return alpha, beta

    def _create_locations(self):
        loc1 = Location.objects.create(name='Location1', data={'prop1': '1', 'prop2': 'test_value'}, point=self.pnt1)
        loc2 = Location.objects.create(name='Location2', data={'prop1': '2', 'prop2': 'test_value'}, point=self.pnt2)
        return loc1, loc2

    def _create_bitfield_bags(self):
        # create dictionaries with bits as dictionary keys (i.e. bag5 = { 'b0':'1', 'b2':'1'})
        for i in xrange(10):
            DataBag.objects.create(name='bag%d' % (i,),
                                   data=dict(('b%d' % (bit,), '1') for bit in xrange(4) if (1 << bit) & i))

    def test_number(self):
        databag = DataBag(name='number')
        databag.data['num'] = 1
        self.assertEqual(databag.data['num'], '1')
        
        databag.save()
        databag = DataBag.objects.get(name='number')
        self.assertEqual(databag.data['num'], '1')
        
        databag = DataBag(name='number', data={ 'num': 1 })
        self.assertEqual(databag.data['num'], '1')
    
    def test_list(self):
        databag = DataBag.objects.create(name='list', data={ 'list': ['a', 'b', 'c'] })
        databag = DataBag.objects.get(name='list')
        self.assertEqual(json.loads(databag.data['list']), ['a', 'b', 'c'])
    
    def test_dictionary(self):
        databag = DataBag.objects.create(name='dict', data={ 'dict': {'subkey': 'subvalue'} })
        databag = DataBag.objects.get(name='dict')
        self.assertEqual(json.loads(databag.data['dict']), {'subkey': 'subvalue'})
    
    def test_boolean(self):
        databag = DataBag.objects.create(name='boolean', data={ 'boolean': True })
        databag = DataBag.objects.get(name='boolean')
        self.assertEqual(json.loads(databag.data['boolean']), True)

    def test_empty_instantiation(self):
        bag = DataBag.objects.create(name='bag')
        self.assertTrue(isinstance(bag.data, dict))
        self.assertEqual(bag.data, {})

    def test_empty_querying(self):
        DataBag.objects.create(name='bag')
        self.assertTrue(DataBag.objects.get(data={}))
        self.assertTrue(DataBag.objects.filter(data={}))
        self.assertTrue(DataBag.objects.filter(data__contains={}))

    def test_named_querying(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.get(name='alpha'), alpha)
        self.assertEqual(DataBag.objects.filter(name='beta')[0], beta)

    def test_aggregates(self):
        self._create_bitfield_bags()

        self.assertEqual(DataBag.objects.filter(data__contains={'b0': '1'}).aggregate(Count('id'))['id__count'], 5)
        self.assertEqual(DataBag.objects.filter(data__contains={'b1': '1'}).aggregate(Count('id'))['id__count'], 4)

    def test_annotations(self):
        self._create_bitfield_bags()

        self.assertEqual(DataBag.objects.annotate(num_id=Count('id')).filter(num_id=1)[0].num_id, 1)

    def test_nested_filtering(self):
        self._create_bitfield_bags()

        # Test cumulative successive filters for both dictionaries and other fields
        f = DataBag.objects.all()
        self.assertEqual(10, f.count())
        f = f.filter(data__contains={'b0': '1'})
        self.assertEqual(5, f.count())
        f = f.filter(data__contains={'b1': '1'})
        self.assertEqual(2, f.count())
        f = f.filter(name='bag3')
        self.assertEqual(1, f.count())

    def test_unicode_processing(self):
        greets = {
            u'de': u'Gr\xfc\xdfe, Welt',
            u'en': u'hello, world',
            u'es': u'hola, ma\xf1ana',
            u'he': u'\u05e9\u05dc\u05d5\u05dd, \u05e2\u05d5\u05dc\u05dd',
            u'jp': u'\u3053\u3093\u306b\u3061\u306f\u3001\u4e16\u754c',
            u'zh': u'\u4f60\u597d\uff0c\u4e16\u754c',
        }
        DataBag.objects.create(name='multilang', data=greets)
        self.assertEqual(greets, DataBag.objects.get(name='multilang').data)

    def test_query_escaping(self):
        me = self

        def readwrite(s):
            # try create and query with potentially illegal characters in the field and dictionary key/value
            o = DataBag.objects.create(name=s, data={s: s})
            me.assertEqual(o, DataBag.objects.get(name=s, data={s: s}))
        readwrite('\' select')
        readwrite('% select')
        readwrite('\\\' select')
        readwrite('-- select')
        readwrite('\n select')
        readwrite('\r select')
        readwrite('* select')

    def test_replace_full_dictionary(self):
        DataBag.objects.create(name='foo', data={'change': 'old value', 'remove': 'baz'})

        replacement = {'change': 'new value', 'added': 'new'}
        DataBag.objects.filter(name='foo').update(data=replacement)
        self.assertEqual(replacement, DataBag.objects.get(name='foo').data)

    def test_equivalence_querying(self):
        alpha, beta = self._create_bags()
        for bag in (alpha, beta):
            data = {'v': bag.data['v'], 'v2': bag.data['v2']}
            self.assertEqual(DataBag.objects.get(data=data), bag)
            r = DataBag.objects.filter(data=data)
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)

    def test_key_value_subset_querying(self):
        alpha, beta = self._create_bags()
        for bag in (alpha, beta):
            r = DataBag.objects.filter(data__contains={'v': bag.data['v']})
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)
            r = DataBag.objects.filter(data__contains={'v': bag.data['v'], 'v2': bag.data['v2']})
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)

    def test_value_in_subset_querying(self):
        alpha, beta = self._create_bags()
        r = DataBag.objects.filter(data__contains={'v': [alpha.data['v']]})
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0], alpha)
        r = DataBag.objects.filter(data__contains={'v': [alpha.data['v'], beta.data['v']]})
        self.assertEqual(len(r), 2)
        self.assertEqual(set(r), set([alpha, beta]))

        # int values are ok
        r = DataBag.objects.filter(data__contains={'v': [int(alpha.data['v'])]})
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0], alpha)

    def test_key_value_gt_querying(self):
        alpha, beta = self._create_bags()
        self.assertGreater(beta.data['v'], alpha.data['v'])
        r = DataBag.objects.filter(data__gt={'v': alpha.data['v']})
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0], beta)
        r = DataBag.objects.filter(data__gte={'v': alpha.data['v']})
        self.assertEqual(len(r), 2)

    def test_key_value_lt_querying(self):
        alpha, beta = self._create_bags()
        self.assertLess(alpha.data['v'], beta.data['v'])
        r = DataBag.objects.filter(data__lt={'v': beta.data['v']})
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0], alpha)
        r = DataBag.objects.filter(data__lte={'v': beta.data['v']})
        self.assertEqual(len(r), 2)

    def test_multiple_key_subset_querying(self):
        alpha, beta = self._create_bags()
        for keys in (['v'], ['v', 'v2']):
            self.assertEqual(DataBag.objects.filter(data__contains=keys).count(), 2)
        for keys in (['v', 'nv'], ['n1', 'n2']):
            self.assertEqual(DataBag.objects.filter(data__contains=keys).count(), 0)

    def test_single_key_querying(self):
        alpha, beta = self._create_bags()
        for key in ('v', 'v2'):
            self.assertEqual(DataBag.objects.filter(data__contains=key).count(), 2)
        for key in ('n1', 'n2'):
            self.assertEqual(DataBag.objects.filter(data__contains=key).count(), 0)

    def test_hkeys(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.hkeys(id=alpha.id, attr='data'), ['v', 'v2'])
        self.assertEqual(DataBag.objects.hkeys(id=beta.id, attr='data'), ['v', 'v2'])

    def test_hpeek(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.hpeek(id=alpha.id, attr='data', key='v'), '1')
        self.assertEqual(DataBag.objects.filter(id=alpha.id).hpeek(attr='data', key='v'), '1')
        self.assertEqual(DataBag.objects.hpeek(id=alpha.id, attr='data', key='invalid'), None)

    def test_hremove(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.get(name='alpha').data, alpha.data)
        DataBag.objects.filter(name='alpha').hremove('data', 'v2')
        self.assertEqual(DataBag.objects.get(name='alpha').data, {'v': '1'})

        self.assertEqual(DataBag.objects.get(name='beta').data, beta.data)
        DataBag.objects.filter(name='beta').hremove('data', ['v', 'v2'])
        self.assertEqual(DataBag.objects.get(name='beta').data, {})

    def test_hslice(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.hslice(id=alpha.id, attr='data', keys=['v']), {'v': '1'})
        self.assertEqual(DataBag.objects.filter(id=alpha.id).hslice(attr='data', keys=['v']), {'v': '1'})
        self.assertEqual(DataBag.objects.hslice(id=alpha.id, attr='data', keys=['ggg']), {})

    def test_hupdate(self):
        alpha, beta = self._create_bags()
        self.assertEqual(DataBag.objects.get(name='alpha').data, alpha.data)
        DataBag.objects.filter(name='alpha').hupdate('data', {'v2': '10', 'v3': '20'})
        self.assertEqual(DataBag.objects.get(name='alpha').data, {'v': '1', 'v2': '10', 'v3': '20'})

    def test_location_create(self):
        l1, l2 = self._create_locations()
        other_loc = Location.objects.get(point__contains=self.pnt1)
        self.assertEqual(other_loc.data, {'prop1': '1', 'prop2': 'test_value'})

    def test_location_hupdate(self):
        l1, l2 = self._create_locations()
        Location.objects.filter(point__contains=self.pnt1).hupdate('data', {'prop1': '2'})
        loc = Location.objects.exclude(point__contains=self.pnt2)[0]
        self.assertEqual(loc.data, {'prop1': '2', 'prop2': 'test_value'})
        loc = Location.objects.get(point__contains=self.pnt2)
        self.assertNotEqual(loc.data, {'prop1': '1', 'prop2': 'test_value'})
    def test_default(self):
        m = DefaultsModel()
        m.save()

    def test_bad_default(self):
        m = BadDefaultsModel()
        try:
            m.save()
        except IntegrityError:
            transaction.rollback()
        else:
            self.assertTrue(False)

    def test_serialization_deserialization(self):
        alpha, beta = self._create_bags()
        self.assertEqual(json.loads(str(DataBag.objects.get(name='alpha').data)), json.loads(str(alpha.data)))
        self.assertEqual(json.loads(str(DataBag.objects.get(name='beta').data)), json.loads(str(beta.data)))


class TestReferencesField(TestCase):
    pnt1 = GEOSGeometry('POINT(65.5758316 57.1345383)')
    pnt2 = GEOSGeometry('POINT(65.2316 57.3423233)')

    def setUp(self):
        Ref.objects.all().delete()
        RefsBag.objects.all().delete()
        Location.objects.all().delete()

    def _create_bags(self):
        refs = [Ref.objects.create(name=str(i)) for i in range(4)]
        alpha = RefsBag.objects.create(name='alpha', refs={'0': refs[0], '1': refs[1]})
        beta = RefsBag.objects.create(name='beta', refs={'0': refs[2], '1': refs[3]})
        return alpha, beta, refs

    def _create_locations(self):
        loc1 = Location.objects.create(name='Location1', data={'prop1': '1', 'prop2': 'test_value'}, point=self.pnt1)
        loc2 = Location.objects.create(name='Location2', data={'prop1': '2', 'prop2': 'test_value'}, point=self.pnt2)
        return loc1, loc2

    def test_empty_instantiation(self):
        bag = RefsBag.objects.create(name='bag')
        self.assertTrue(isinstance(bag.refs, dict))
        self.assertEqual(bag.refs, {})

    def test_empty_querying(self):
        RefsBag.objects.create(name='bag')
        self.assertTrue(RefsBag.objects.get(refs={}))
        self.assertTrue(RefsBag.objects.filter(refs={}))
        self.assertTrue(RefsBag.objects.filter(refs__contains={}))

    def test_equivalence_querying(self):
        alpha, beta, refs = self._create_bags()
        for bag in (alpha, beta):
            refs = {'0': bag.refs['0'], '1': bag.refs['1']}
            self.assertEqual(RefsBag.objects.get(refs=refs), bag)
            r = RefsBag.objects.filter(refs=refs)
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)

    def test_key_value_subset_querying(self):
        alpha, beta, refs = self._create_bags()
        for bag in (alpha, beta):
            r = RefsBag.objects.filter(refs__contains={'0': bag.refs['0']})
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)
            r = RefsBag.objects.filter(refs__contains={'0': bag.refs['0'], '1': bag.refs['1']})
            self.assertEqual(len(r), 1)
            self.assertEqual(r[0], bag)

    def test_multiple_key_subset_querying(self):
        alpha, beta, refs = self._create_bags()
        for keys in (['0'], ['0', '1']):
            self.assertEqual(RefsBag.objects.filter(refs__contains=keys).count(), 2)
        for keys in (['0', 'nv'], ['n1', 'n2']):
            self.assertEqual(RefsBag.objects.filter(refs__contains=keys).count(), 0)

    def test_single_key_querying(self):
        alpha, beta, refs = self._create_bags()
        for key in ('0', '1'):
            self.assertEqual(RefsBag.objects.filter(refs__contains=key).count(), 2)
        for key in ('n1', 'n2'):
            self.assertEqual(RefsBag.objects.filter(refs__contains=key).count(), 0)

    def test_hkeys(self):
        alpha, beta, refs = self._create_bags()
        self.assertEqual(RefsBag.objects.hkeys(id=alpha.id, attr='refs'), ['0', '1'])

    def test_hpeek(self):
        alpha, beta, refs = self._create_bags()
        self.assertEqual(RefsBag.objects.hpeek(id=alpha.id, attr='refs', key='0'), refs[0])
        self.assertEqual(RefsBag.objects.filter(id=alpha.id).hpeek(attr='refs', key='0'), refs[0])
        self.assertEqual(RefsBag.objects.hpeek(id=alpha.id, attr='refs', key='invalid'), None)

    def test_hslice(self):
        alpha, beta, refs = self._create_bags()
        self.assertEqual(RefsBag.objects.hslice(id=alpha.id, attr='refs', keys=['0']), {'0': refs[0]})
        self.assertEqual(RefsBag.objects.filter(id=alpha.id).hslice(attr='refs', keys=['0']), {'0': refs[0]})
        self.assertEqual(RefsBag.objects.hslice(id=alpha.id, attr='refs', keys=['invalid']), {})

    def test_location_create(self):
        l1, l2 = self._create_locations()
        loc_1 = Location.objects.get(point__contains=self.pnt1)
        self.assertEqual(loc_1.data, {'prop1': '1', 'prop2': 'test_value'})
        loc_2 = Location.objects.get(point__contains=self.pnt2)
        self.assertEqual(loc_2.data, {'prop1': '2', 'prop2': 'test_value'})

    def test_location_hupdate(self):
        l1, l2 = self._create_locations()
        Location.objects.filter(point__contains=self.pnt1).hupdate('data', {'prop1': '2'})
        loc = Location.objects.exclude(point__contains=self.pnt2)[0]
        self.assertEqual(loc.data, {'prop1': '2', 'prop2': 'test_value'})
        loc = Location.objects.get(point__contains=self.pnt2)
        self.assertNotEqual(loc.data, {'prop1': '1', 'prop2': 'test_value'})
