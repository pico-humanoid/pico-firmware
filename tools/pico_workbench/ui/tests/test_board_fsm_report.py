"""Verify that explanations follow actual serial evidence, including failures."""
from collections import deque
from io import StringIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from board_fsm_protocol import Bench, VERIFY_STEPS, verify
from board_fsm_report import CASES, FsmReport, led_text


def state(mode="ZERO_TORQUE", acks=3, *, target=None, pending=0, fault="NONE", ms=1000):
    return (f"# FSM_STATE,t_ms={ms},source=SIMULATED,state={mode},target={target or mode},"
            f"pending={pending},ack1={acks & 1},ack2={(acks >> 1) & 1},fault={fault},drop_next=0")


class SimulatedBoard:
    """Serial peer for protocol tests only; no hardware or real serial port."""
    def __init__(self, fail_test=False, fragment=False, legacy_debug=False):
        self.legacy_debug = legacy_debug
        self.mode, self.drop, self.fault = "ZERO_TORQUE", False, False
        self.messages, self.commands = deque(), []
        self.fail_test, self.fragment = fail_test, fragment
        self.queue(state())

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def queue(self, *lines):
        for line in lines:
            raw = (line + "\r\n").encode("ascii")
            if self.fragment:
                self.messages.extend((raw[:20], raw[20:]))
            else:
                self.messages.append(raw)

    def readline(self, _limit):
        if not self.messages:
            self.queue(state(self.mode, 1 if self.fault else 3, target="DAMPING" if self.fault else self.mode,
                             fault="MODE_TIMEOUT" if self.fault else "NONE"))
        return self.messages.popleft()

    def write(self, raw):
        command = raw.decode("ascii").strip()
        self.commands.append(command)

        def reply(result):
            self.queue(f"# FSM_REPLY,command={command},result={result}")

        if command == "RESET":
            self.fault, self.mode = False, "ZERO_TORQUE"
            self.queue(state("SELF_CHECK", 0, target="ZERO_TORQUE", pending=1),
                       state("SELF_CHECK", 1, target="ZERO_TORQUE", pending=1), state())
        elif command == "TEST":
            for name in CASES:
                self.queue(f"# FSM_CASE,{name},{'FAIL' if self.fail_test else 'PASS'}")
            self.queue(f"# FSM_TEST_RESULT={'FAIL' if self.fail_test else 'PASS'},scope=BOARD_LOGIC_ONLY")
        elif command == "DEBUG" and self.legacy_debug:
            reply("DEBUG_RESERVED")
            self.queue(state(self.mode))
        elif command == "MISS2":
            self.drop = True
            reply("ARMED_FOR_NEXT_TRANSITION")
        elif self.fault:
            reply("FAULT_LOCKED")
            self.queue(state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT"))
        elif command in ("DAMP", "ZERO", "DEBUG"):
            target = {"DAMP": "DAMPING", "ZERO": "ZERO_TORQUE", "DEBUG": "DEBUG_RESERVED"}[command]
            reply("ACCEPTED")
            self.queue(state(self.mode, 0, target=target, pending=1),
                       state(self.mode, 1, target=target, pending=1))
            if self.drop:
                self.drop, self.fault, self.mode = False, True, "FAULT_LOCKED"
                self.queue(state("FAULT_LOCKED", 1, target=target, fault="MODE_TIMEOUT"))
            else:
                self.mode = target
                self.queue(state(target))
        return len(raw)


class BoardFsmReadabilityTests(unittest.TestCase):
    def make_report(self):
        log, output, steps = StringIO(), [], []
        report = FsmReport(log, output.append, lambda *event: steps.append(event))
        return report, log, output, steps

    def test_complete_acceptance_reports_all_steps_and_expected_fault(self):
        report, human, _, steps = self.make_report()
        raw, board = StringIO(), SimulatedBoard(fragment=True)
        verify(Bench(board, raw, on_line=report.receive, on_command=report.command, on_step=report.step))
        report.finish("PASS")
        self.assertEqual([e[0] for e in steps if e[1] == "PASS"], list(range(1, 9)))
        self.assertEqual(board.commands, ["RESET", "TEST", "DAMP", "ZERO", "DEBUG", "MISS2", "DAMP", "ZERO", "DEBUG", "RESET"])
        self.assertIn("[故障注入] MISS2", human.getvalue())
        self.assertIn("[预期保护]", human.getvalue())
        self.assertIn("当前调试预留，不再等待确认", human.getvalue())
        self.assertIn("[整体验证通过]", human.getvalue())
        self.assertNotIn("[异常报警]", human.getvalue())
        self.assertIn("# FSM_STATE,", raw.getvalue())
        self.assertNotIn("[状态到达]", raw.getvalue())

    def test_counted_led_firmware_allows_viewing_states_before_next_command(self):
        class CountedBoard(SimulatedBoard):
            def queue(self, *lines):
                super().queue(*(line + ",led_scheme=COUNTED" if line.startswith("# FSM_STATE,") else line
                                for line in lines))

        report, log, _, steps = self.make_report()
        board = CountedBoard(fragment=True)
        observed = []

        def observe(fields, seconds):
            observed.append((fields["state"], seconds, board.commands[-1]))

        bench = Bench(board, StringIO(), on_line=report.receive, on_command=report.command, on_step=report.step)
        ticks = iter(n * 0.05 for n in range(1000))
        with patch("board_fsm_protocol.time.monotonic", side_effect=lambda: next(ticks)):
            verify(bench, on_observe=observe)
        self.assertEqual(observed, [("ZERO_TORQUE", 3, "TEST"), ("DAMPING", 3, "DAMP"),
                                    ("DEBUG_RESERVED", 3, "DEBUG"), ("FAULT_LOCKED", 3, "DEBUG")])
        self.assertIn("用户灯熄灭", log.getvalue())
        for count, mode in enumerate(("ZERO_TORQUE", "DAMPING", "DEBUG_RESERVED"), 1):
            self.assertIn(f"用户灯每组闪 {count} 下", log.getvalue())
            self.assertEqual(led_text({"state": mode, "pending": "1", "led_scheme": "COUNTED"}), "熄灭")
        self.assertEqual(steps[-1][:2], (8, "PASS"))

    def test_old_debug_reply_does_not_count_as_state_transition(self):
        report, log, _, steps = self.make_report()
        board = SimulatedBoard(legacy_debug=True)
        with self.assertRaisesRegex(RuntimeError, "只返回标记"):
            verify(Bench(board, StringIO(), on_line=report.receive, on_step=report.step))
        self.assertEqual(steps[-1][:2], (5, "FAIL"))
        self.assertNotIn("[状态到达] 当前调试预留", log.getvalue())

    def test_internal_pass_is_not_whole_experiment_pass(self):
        report, log, _, _ = self.make_report()
        report.receive("# FSM_TEST_RESULT=PASS,scope=BOARD_LOGIC_ONLY")
        self.assertIn("这不是整套串口验证的最终结果", log.getvalue())
        self.assertNotIn("[整体验证通过]", log.getvalue())
        report.finish("PASS")
        self.assertIn("[整体验证失败]", log.getvalue())

    def test_unexpected_fault_and_wrong_fault_during_injection_remain_alarms(self):
        report, log, _, _ = self.make_report()
        report.receive(state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT"))
        self.assertIn("[异常报警]", log.getvalue())
        report.step(1, "RUNNING")
        report.step(6, "RUNNING")
        report.receive(state("FAULT_LOCKED", 1, target="ZERO_TORQUE", fault="LOCAL_CHECK_FAILED"))
        self.assertEqual(log.getvalue().count("[异常报警]"), 2)
        self.assertNotIn("[预期保护]", log.getvalue())

    def test_failed_builtin_check_marks_only_current_step_failed(self):
        report, log, _, steps = self.make_report()
        board = SimulatedBoard(fail_test=True)
        with self.assertRaisesRegex(RuntimeError, "内置逻辑检查未通过"):
            verify(Bench(board, StringIO(), on_line=report.receive, on_command=report.command, on_step=report.step))
        report.finish("FAIL")
        self.assertEqual(steps[-1][0:2], (2, "FAIL"))
        self.assertNotIn("DAMP", board.commands)
        self.assertNotIn("[整体验证通过]", log.getvalue())

    def test_pending_confirmation_is_not_reported_as_reached_mode(self):
        report, log, _, _ = self.make_report()
        report.receive(state("ZERO_TORQUE", 1, target="DAMPING", pending=1))
        self.assertIn("[等待确认]", log.getvalue())
        self.assertIn("切换尚未完成", log.getvalue())
        self.assertIn("模拟电机2=未确认", log.getvalue())
        self.assertNotIn("[状态到达]", log.getvalue())

    def test_heartbeats_are_throttled_but_not_state_changes(self):
        report, log, _, _ = self.make_report()
        with patch("board_fsm_report.time.monotonic", side_effect=[1, 2, 12, 13]):
            report.receive(state())
            report.receive(state(ms=2000))
            report.receive(state(ms=12000))
            report.receive(state("DAMPING", ms=13000))
        self.assertEqual(len(log.getvalue().splitlines()), 3)
        self.assertIn("[状态心跳]", log.getvalue())
        self.assertIn("用户灯慢闪", log.getvalue())

    def test_invalid_state_is_identified_and_does_not_claim_success(self):
        report, log, _, _ = self.make_report()
        report.receive("# FSM_STATE,t_ms=bad,state=ZERO_TORQUE,ack1=1")
        self.assertIn("[异常报警]", log.getvalue())
        self.assertNotIn("[状态到达]", log.getvalue())

    def test_timeout_names_expected_state_in_chinese_and_marks_step(self):
        report, _, _, steps = self.make_report()

        class SilentBoard:
            def readline(self, _limit):
                return b""

        with patch("board_fsm_protocol.time.monotonic", side_effect=[0, 5]):
            with self.assertRaisesRegex(RuntimeError, "等待超时.*识别 BoardFsm"):
                verify(Bench(SilentBoard(), StringIO(), on_step=report.step))
        self.assertEqual(steps[-1][0:2], (1, "FAIL"))

    def test_discarded_reset_is_reported_immediately_as_input_error(self):
        report, log, _, steps = self.make_report()

        class DiscardedReset(SimulatedBoard):
            def write(self, raw):
                self.commands.append(raw.decode("ascii").strip())
                self.queue("# FSM_REPLY,command=INVALID_LINE,result=DISCARDED")
                return len(raw)

        board = DiscardedReset()
        with self.assertRaisesRegex(RuntimeError, "本条指令未执行"):
            verify(Bench(board, StringIO(), on_line=report.receive, on_command=report.command, on_step=report.step))
        self.assertEqual(steps[-1][0:2], (1, "FAIL"))
        self.assertEqual(board.commands, ["RESET"])
        self.assertIn("[异常报警]", log.getvalue())
        self.assertNotIn("[预期保护]", log.getvalue())

    def test_recovery_drains_status_frame_after_rejected_zero(self):
        class BoardWithTrailingStatus(SimulatedBoard):
            def write(self, raw):
                if raw == b"RESET\n" and self.fault:
                    # Model the old firmware losing input while transmitting its status.
                    if self.messages:
                        raise AssertionError("RESET sent while ZERO's state frame was still in flight")
                    self.queue("# FSM_REPLY,command=RESET,result=ACCEPTED")
                return super().write(raw)

        board = BoardWithTrailingStatus(fragment=True)
        report, _, _, steps = self.make_report()
        verify(Bench(board, StringIO(), on_step=report.step))
        self.assertEqual(steps[-1][:2], (8, "PASS"))

    def test_recovery_requires_fresh_self_check_even_after_reset_ack(self):
        class AcceptedButStillLocked(SimulatedBoard):
            def write(self, raw):
                if raw == b"RESET\n" and self.fault:
                    self.queue("# FSM_REPLY,command=RESET,result=ACCEPTED",
                               state("FAULT_LOCKED", 1, target="DAMPING", fault="MODE_TIMEOUT"))
                    return len(raw)
                return super().write(raw)

        board = AcceptedButStillLocked()
        report, _, _, steps = self.make_report()
        ticks = iter(n * 0.05 for n in range(1000))
        with patch("board_fsm_protocol.time.monotonic", side_effect=lambda: next(ticks)):
            with self.assertRaisesRegex(RuntimeError, "未观察到自检开始"):
                verify(Bench(board, StringIO(), on_step=report.step))
        self.assertEqual(steps[-1][:2], (8, "FAIL"))


if __name__ == "__main__":
    unittest.main()
