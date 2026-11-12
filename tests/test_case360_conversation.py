"""Analyst flow through real NiceGUI elements; private transport is a synthetic double."""
import asyncio

from nicegui import core

from casefinder.ui import case360_conversation as flow


def test_landing_has_one_text_field_and_no_configuration(render, monkeypatch):
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    tree = render(flow.render)
    assert len(tree.of_type("Textarea")) == 1
    assert not tree.of_type("Select")
    assert not tree.of_type("Number")
    assert "Beta settings" in tree.text
    assert "$50 USD" in tree.text
    assert "Prepare request" not in tree.button_labels()
    assert "Check connection" not in tree.button_labels()


def test_blank_request_is_explained_without_protocol_call(render, monkeypatch):
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    monkeypatch.setattr(flow.session, "client", lambda: (_ for _ in ()).throw(
        AssertionError("Blank input must not start the controller")))
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            tree.press(next(b for b in tree.buttons() if b.text == "Analyze request"))
            await asyncio.sleep(0)
        assert "Enter a request" in tree.text

    asyncio.run(check())


def test_answer_is_sent_with_question_id_and_remaining_budget(render, monkeypatch):
    class Client:
        def __init__(self):
            self.calls = []
            self.round = 0
            self.started = False

        def view(self):
            return {"run_id": f"run-{self.round}", "contract_sha256": "a" * 64,
                    "execution_status": "COMPLETED" if self.started else "DRAFT",
                    "artifact": {"artifact_id": "result", "sha256": "b" * 64}}

        async def request(self, method, params=None, **kwargs):
            self.calls.append((method, params, kwargs))
            if method == "prepare_conversation":
                self.round += 1
                self.started = False
            if method == "probe_run":
                return {"sha256": "c" * 64, "max_paid_usd": 50}
            if method == "start_run":
                self.started = True
            return self.view()

        async def artifact(self, run_id, reference):
            conversation = {"waiting": self.round == 1, "original_text": "Synthetic request"}
            if not self.started:
                return {"resources": {}, "source_evidence": {"sources": []}}
            return {"conversation": conversation, "execution_status": "COMPLETED",
                    "quality_status": "HOLD", "interpretation": "I need a date.",
                    "questions": [{"id": "intake-year", "text": "Which year?"}],
                    "budget": {"cap_usd": 50, "charged_or_reserved_usd": 1,
                               "remaining_usd": 49, "uncertain_reservation_usd": 0},
                    "packages": [] if self.round == 1 else [{"version": 1,
                        "package": {"cohort": {"sql": "SELECT 2024 AS requested_year"}}}]}

    client = Client()
    monkeypatch.setattr(flow.session, "client", lambda: client)
    monkeypatch.setattr(flow, "configured_cap", lambda: 50)
    monkeypatch.setattr(flow, "active_request", lambda *a, **kw: None)
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, "loop", asyncio.get_running_loop())
        with tree.client:
            tree.of_type("Textarea")[0].value = "Synthetic request"
            tree.press(next(b for b in tree.buttons() if b.text == "Analyze request"))
            await asyncio.sleep(0)
            assert "Which year?" in tree.text
            assert not any("SELECT" in str(e._props) for e in tree.of_type("Code"))
            tree.of_type("Textarea")[-1].value = "2024"
            tree.press(next(b for b in tree.buttons() if b.text == "Continue with my answers"))
            await asyncio.sleep(0)
        prepares = [p for m, p, _ in client.calls if m == "prepare_conversation"]
        assert prepares == [
            {"text": "Synthetic request", "previous_run_id": None, "answers": []},
            {"text": "", "previous_run_id": "run-1",
             "answers": [{"question_id": "intake-year", "text": "2024"}]}]
        assert [p["cap_usd"] for m, p, _ in client.calls if m == "authorize_run"] == [50, 49]
        assert "SQL is ready" in tree.text
        assert "SELECT 2024 AS requested_year" in tree.text

    asyncio.run(check())


def test_internal_failure_keeps_request_without_connection_retry(render, monkeypatch):
    from casefinder.case360.client import BridgeError

    class Client:
        async def request(self, method, params=None, **kwargs):
            if method == 'authorize_run':
                raise BridgeError('FREEZE_REQUEST_FAILED', 'Incompatible or incomplete request.')
            if method == 'probe_run':
                return {'sha256': 'b' * 64, 'max_paid_usd': 50}
            return {'run_id': 'saved-request', 'contract_sha256': 'a' * 64,
                    'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'resources': {}, 'source_evidence': {}}

    monkeypatch.setattr(flow.session, 'client', Client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow, 'active_request', lambda *a, **kw: None)
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
        with tree.client:
            tree.of_type('Textarea')[0].value = 'Synthetic request with an unresolved date'
            tree.press(next(b for b in tree.buttons() if b.text == 'Analyze request'))
            await asyncio.sleep(0)
        assert 'Update or repair the beta' in tree.text
        assert 'Your request is saved' in tree.text
        assert not any('Retry' in text for text in tree.button_labels())
        assert tree.of_type('Textarea')[0].value == 'Synthetic request with an unresolved date'

    asyncio.run(check())


def test_connection_retry_reuses_saved_request_and_explains_continuation(render, monkeypatch):
    from casefinder.case360.client import BridgeError

    class Client:
        def __init__(self):
            self.calls = []

        async def request(self, method, params=None, **kwargs):
            self.calls.append((method, kwargs.get('run_id')))
            if method == 'probe_run':
                raise BridgeError('PREFLIGHT_TIMEOUT', 'Connection check timed out.')
            return {'run_id': 'saved-request', 'contract_sha256': 'a' * 64,
                    'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'resources': {}, 'source_evidence': {}}

    client = Client()
    monkeypatch.setattr(flow.session, 'client', lambda: client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow, 'active_request', lambda *a, **kw: None)
    tree = render(flow.render)

    async def check():
        monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
        with tree.client:
            tree.of_type('Textarea')[0].value = 'Synthetic request'
            tree.press(next(b for b in tree.buttons() if b.text == 'Analyze request'))
            await asyncio.sleep(0)
            assert 'then continues the request' in tree.text
            tree.press(next(b for b in tree.buttons() if b.text == 'Retry and continue'))
            await asyncio.sleep(0)
        assert [m for m, _ in client.calls].count('prepare_conversation') == 1
        assert [r for m, r in client.calls if m == 'probe_run'] == ['saved-request'] * 2
        assert not any(m in {'authorize_run', 'start_run'} for m, _ in client.calls)

    asyncio.run(check())


def test_reopening_draft_preserves_literal_text_without_starting_analysis(render, monkeypatch):
    text = 'Synthetic request, exactly as entered.  \n'
    timers = []
    calls = []

    class Client:
        async def request(self, method, **kwargs):
            calls.append(method)
            assert method == 'get_run'
            return {'execution_status': 'READY', 'authorized': False,
                    'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'conversation': {'original_text': text, 'remaining_cap_usd': 50}}

    monkeypatch.setattr(flow.session, 'client', Client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow.ui, 'timer', lambda interval, callback, **kw: timers.append(callback))
    tree = render(lambda: flow.render(run_id='saved-request'))

    async def check():
        with tree.client:
            await timers[0]()
        assert tree.of_type('Textarea')[0].value == text
        assert 'Continue this request' in tree.button_labels()
        assert calls == ['get_run']

    asyncio.run(check())


def test_recovered_questions_take_priority_over_failed_sql_panel(render, monkeypatch):
    timers = []
    text = 'Synthetic request, preserved.  \n'
    calls = []

    class Client:
        async def request(self, method, **kwargs):
            calls.append(method)
            return {'execution_status': 'FAILED', 'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'execution_status': 'FAILED', 'conversation': {'waiting': True,
                    'original_text': text}, 'clarification_recovery': {'additional_model_calls': 0},
                    'questions': [{'id': 'q1', 'text': 'Which year?'}],
                    'budget': {'charged_or_reserved_usd': .1715, 'remaining_usd': 49.8285},
                    'interpretation': 'The year needs clarification.', 'packages': []}

    monkeypatch.setattr(flow.session, 'client', Client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow.ui, 'timer', lambda interval, callback, **kw: timers.append(callback))
    tree = render(lambda: flow.render(run_id='saved-request'))

    async def check():
        with tree.client:
            await timers[0]()
        assert tree.of_type('Textarea')[0].value == text
        assert 'Which year?' in tree.text
        assert 'No new model call was needed' in tree.text
        assert 'Continue with my answers' in tree.button_labels()
        assert '$49.83' in tree.text
        assert not tree.of_type('Tabs')
        assert calls == ['get_run']

    asyncio.run(check())


def test_continue_disables_duplicate_click_while_connection_is_pending(render, monkeypatch):
    timers = []
    calls = []

    class Client:
        async def request(self, method, params=None, **kwargs):
            calls.append(method)
            if method == 'probe_run':
                await asyncio.Event().wait()
            return {'run_id': 'saved', 'execution_status': 'READY', 'authorized': False,
                    'contract_sha256': 'a' * 64, 'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'conversation': {'original_text': 'Synthetic', 'remaining_cap_usd': 50}}

    monkeypatch.setattr(flow.session, 'client', Client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow.ui, 'timer', lambda interval, callback, **kw: timers.append(callback))
    tree = render(lambda: flow.render(run_id='saved'))

    async def check():
        monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
        with tree.client:
            await timers[0]()
            button = next(b for b in tree.buttons() if b.text == 'Continue this request')
            tree.press(button)
            await asyncio.sleep(0)
            assert not button.enabled
            assert 'Checking your connection' in tree.text
        assert calls.count('probe_run') == 1

    asyncio.run(check())


def test_context_recovery_restores_answers_and_offers_saved_progress(render, monkeypatch):
    timers = []
    calls = []

    class Client:
        async def request(self, method, params=None, **kwargs):
            calls.append((method, params))
            if method == 'prepare_conversation':
                await asyncio.Event().wait()
            return {'execution_status': 'FAILED', 'artifact': {'artifact_id': 'result'}}

        async def artifact(self, *args):
            return {'execution_status': 'FAILED', 'packages': [],
                    'conversation': {'original_text': 'Original request  \n',
                                     'spent_before_usd': .17,
                                     'answers': [{'question': 'Which year?', 'text': '2024'}]},
                    'continuation_recovery': {'available': True},
                    'interpretation': 'Use the saved year.',
                    'budget': {'charged_or_reserved_usd': .61, 'remaining_usd': 49.22}}

    monkeypatch.setattr(flow.session, 'client', Client)
    monkeypatch.setattr(flow, 'configured_cap', lambda: 50)
    monkeypatch.setattr(flow.ui, 'timer', lambda interval, callback, **kw: timers.append(callback))
    tree = render(lambda: flow.render(run_id='saved-request'))

    async def check():
        monkeypatch.setattr(core, 'loop', asyncio.get_running_loop())
        with tree.client:
            await timers[0]()
            assert tree.of_type('Textarea')[0].value == 'Original request  \n'
            assert '2024' in tree.text
            assert '$49.22' in tree.text
            assert not tree.of_type('Tabs')
            assert calls == [('get_run', None)]
            button = next(b for b in tree.buttons() if b.text == 'Continue from saved progress')
            tree.press(button)
            await asyncio.sleep(0)
            assert not button.enabled
            assert calls[-1] == ('prepare_conversation', {
                'text': '', 'previous_run_id': 'saved-request', 'answers': []})

    asyncio.run(check())
