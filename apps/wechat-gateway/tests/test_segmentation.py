import unittest

from wechat_gateway.messages import segment_messages


class SegmentationTest(unittest.TestCase):
    def test_segment_messages_caps_at_three_lines(self) -> None:
        messages = segment_messages("第一条\n第二条\n第三条\n第四条")
        self.assertEqual([item.content for item in messages], ["第一条", "第二条", "第三条"])

    def test_segment_messages_flattens_single_line(self) -> None:
        messages = segment_messages("先过来   别硬撑")
        self.assertEqual([item.content for item in messages], ["先过来 别硬撑"])


if __name__ == "__main__":
    unittest.main()
