import unittest

from sparkle_gen2.cli import (
    build_parser,
    format_result,
    normalize_request,
)


class Cycle14CLITests(unittest.TestCase):

    def test_chat_prefix_is_natural_alias(self):
        self.assertEqual(
            normalize_request(['chat','organize','my','week']),
            'organize my week'
        )

    def test_plain_request_unchanged(self):
        self.assertEqual(
            normalize_request(['organize','my','week']),
            'organize my week'
        )

    def test_default_output_hides_json_and_verbose_shows_action_summary(self):
        r={
            'text':'done',
            'verified':['Checked state'],
            'approvals':[],
            'gen1_approvals':[],
            'trace_id':'t1',
        }
        self.assertEqual(
            format_result(r,False),
            'done'
        )
        self.assertIn(
            'I completed:',
            format_result(r,True)
        )
        self.assertIn(
            '• Checked state',
            format_result(r,True)
        )
        self.assertIn(
            'Trace: t1',
            format_result(r,True)
        )

    def test_supported_lifecycle_actions_parse(self):
        parser=build_parser()

        cases=[
            ['--resume','goal-1'],
            ['--approve','approval-1'],
            ['--reject','approval-1'],
            ['--cancel','goal-1'],
        ]

        for argv in cases:
            with self.subTest(argv=argv):
                parsed=parser.parse_args(argv)
                self.assertTrue(
                    any(
                        getattr(parsed,name,None)
                        for name in (
                            'resume',
                            'approve',
                            'reject',
                            'cancel',
                        )
                    )
                )

    def test_lifecycle_actions_are_mutually_exclusive(self):
        parser=build_parser()

        cases=[
            ['--approve','a','--reject','b'],
            ['--resume','g','--cancel','g2'],
            ['--resume','g','--approve','a'],
        ]

        for argv in cases:
            with self.subTest(argv=argv):
                with self.assertRaises(SystemExit) as cm:
                    parser.parse_args(argv)
                self.assertEqual(cm.exception.code,2)

    def test_json_and_verbose_are_independent_format_flags(self):
        parser=build_parser()

        parsed=parser.parse_args(
            ['--json','--verbose','status']
        )

        self.assertTrue(parsed.json)
        self.assertTrue(parsed.verbose)
        self.assertEqual(
            parsed.request,
            ['status']
        )

    def test_chat_prefix_normalization_does_not_change_lifecycle_tokens(self):
        parser=build_parser()

        parsed=parser.parse_args(
            ['chat','organize','my','week']
        )

        self.assertEqual(
            normalize_request(parsed.request),
            'organize my week'
        )


if __name__=='__main__':
    unittest.main()