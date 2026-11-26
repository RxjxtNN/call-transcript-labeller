from unittest import TestCase

from detect_caller_gender import detect


def gender(transcript):
    return detect(transcript)[0]


class CallerGenderTests(TestCase):
    def test_self_identification_and_direct_address(self):
        self.assertEqual(gender("Customer: I am a woman calling about my back pain."), "female")
        self.assertEqual(gender("Agent: Okay, sir.\nCustomer: Thank you."), "male")
        self.assertEqual(detect("Agent: Can you hear me, madam?\nCustomer: Yes."),
                         ("female", "Can you hear me, madam?", "agent_address", {"madam": 1}))

    def test_self_identification_beats_an_agent_title(self):
        self.assertEqual(detect("Agent: Hello, sir.\nCustomer: I’m a woman."),
                         ("female", "I'm a woman.", "self_identification", {"sir": 1}))

    def test_references_that_are_not_about_the_caller(self):
        for transcript in ("Agent: I am a woman.\nCustomer: I'm calling for my wife.",
                           "Agent: Sir will give you a call.\nCustomer: Okay.",
                           "Customer: My wife said I am a woman when speaking to the agent.",
                           "Customer: I am a man's caregiver.", "Customer: I am a woman?",
                           "Agent: Mr. Rao will call you.\nCustomer: Thanks.",
                           'Agent: She said "Hi sir, can you help?"\nCustomer: Yes madam.'):
            with self.subTest(transcript=transcript):
                self.assertEqual(gender(transcript), "unknown")

    def test_conflicting_titles_abstain(self):
        for transcript in ("Agent: Hello, sir.\nCustomer: Hello.\nAgent: Okay, madam.\nCustomer: Yes.",
                           "Agent: Hello ma'am.\nAgent: How can I help?\nCustomer: Hello.\nAgent: Okay, sir.\nCustomer: Thanks."):
            with self.subTest(transcript=transcript):
                self.assertEqual(gender(transcript), "unknown")

    def test_greetings_named_address_and_consecutive_agent_turns(self):
        self.assertEqual(detect("Customer: Hello.\nAgent: Hi sir, can you hear me?\nAgent: Thank you sir.")[3], {"sir": 2})
        self.assertEqual(gender("Agent: Hi, Ms. Rao?\nCustomer: Speaking."), "female")

    def test_phone_handoff_stops_attribution(self):
        self.assertEqual(gender("Customer: I'll pass the phone to my father.\nAgent: Hello sir.\nCustomer: Hi."), "unknown")
