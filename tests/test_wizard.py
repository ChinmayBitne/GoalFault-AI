from goalfault.wizard import wizard_messages

def test_wizard_prompt_names_the_spec_keys():
    text = wizard_messages("A library desk for synthetic patrons only.")[0]["content"]
    for key in ("agent_description", "invariant", "safe_controls", "Quote every string"):
        assert key in text
