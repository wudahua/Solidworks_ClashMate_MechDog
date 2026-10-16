import unittest
from unittest.mock import patch

class ExplicitProbeBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_five_second_settings_can_be_requested_explicitly(self):
        import motion_server as server
        with patch.object(server, 'enqueue', return_value={'job_id': 'x'}) as enqueue:
            await server.preflight_motion('m', 'native', True, 5, 25, 'c')
            self.assertEqual(enqueue.call_args.args[1]['duration_s'], 5)
            self.assertEqual(enqueue.call_args.args[1]['output_fps'], 25)

    async def test_default_budget_does_not_expand(self):
        import motion_server as server
        with patch.object(server, 'enqueue', return_value={'job_id': 'x'}) as enqueue:
            await server.preflight_motion('m', 'native', True)
            self.assertEqual(enqueue.call_args.args[1]['duration_s'], 1)

    async def test_invalid_or_unaligned_probes_never_dispatch(self):
        import motion_server as server
        for seconds, fps in ((5.001, 25), (float('nan'), 30), (float('inf'), 30), (0, 25), (5, 121), (1.01, 25)):
            with self.subTest(seconds=seconds, fps=fps), patch.object(server, 'enqueue') as enqueue:
                with self.assertRaises(Exception):
                    await server.preflight_motion('m', 'native', True, seconds, fps)
                enqueue.assert_not_called()

if __name__ == '__main__':
    unittest.main()
