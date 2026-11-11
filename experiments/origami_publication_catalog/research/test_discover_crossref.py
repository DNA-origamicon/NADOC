import unittest
import discover_crossref as C


class CrossrefTests(unittest.TestCase):
    def test_normalized_dedup_preserves_reviewed_record(self):
        existing=[{'doi':'10.1000/one','review_stage':'fulltext_reviewed'}]
        items=[{'DOI':'https://doi.org/10.1000/ONE'},{'DOI':'10.1000/two','title':['New']},{'DOI':'10.1000/TWO'}]
        new=C.page_additions(items,existing,'fixture',{'url':'fixture'})
        self.assertEqual([r['doi'] for r in new],['10.1000/two'])
        self.assertEqual(new[0]['review_stage'],'unreviewed')
        self.assertEqual(existing[0]['review_stage'],'fulltext_reviewed')
        self.assertEqual(C.page_additions(items,existing+new,'fixture',{}),[])

    def test_short_page_is_exhausted_not_provider_total_limit(self):
        self.assertEqual(C.next_state({'items':[{}],'total-results':100000000}),('exhausted',None))

    def test_full_page_requires_cursor(self):
        with self.assertRaises(ValueError):C.next_state({'items':[{}]*C.ROWS})
        self.assertEqual(C.next_state({'items':[{}]*C.ROWS,'next-cursor':'opaque'}),('in_progress','opaque'))

    def test_invalid_identity_fails_before_output(self):
        with self.assertRaises(ValueError):C.page_additions([{'DOI':'not-a-doi'}],[],'fixture',{})


if __name__=='__main__':unittest.main()
