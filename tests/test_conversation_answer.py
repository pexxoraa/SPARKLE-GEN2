import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from sparkle.model import ModelResponse
from sparkle_gen2.conversations import ConversationService
from sparkle_gen2.sessions import SessionService
from sparkle_gen2.storage import Gen2Store

class FakeManager:
    def __init__(self): self.calls=[]
    def complete(self,request,*args,**kwargs):
        self.calls.append((request,args,kwargs))
        return {'response':ModelResponse('Python is a high-level, general-purpose programming language known for readable syntax.','test-model','test','stop'),'route':{'status':'HEALTHY'},'provenance':{'provider':'test','model':'test-model'}}

class FakeAgent:
    def __init__(self): self.gen1=SimpleNamespace(model_manager=FakeManager()); self.last_target=None
    def start(self,text,target_device_id=None): self.last_target=target_device_id; return {'goal_id':'goal-1','text':'task '+text,'status':'COMPLETED'}
    def report(self,*args): return {'goal_id':'goal-1','text':'status','status':'COMPLETED'}

class ConversationAnswerTests(unittest.TestCase):
    def make(self):
        db=tempfile.TemporaryDirectory();store=Gen2Store(Path(db.name)/'g.db');agent=FakeAgent();service=ConversationService(store,SessionService(store),agent);return db,store,agent,service
    def test_knowledge_question_gets_direct_answer_without_goal(self):
        db,store,agent,service=self.make()
        try:
            out=service.send('what is python programming ?')
            self.assertEqual(out['message']['status'],'COMPLETED')
            self.assertIn('high-level',out['message']['text'])
            self.assertNotIn('goal_id',out['message'])
            self.assertIsNone(store.load_session(out['session_id']).active_goal_id)
            self.assertEqual(len(store.recent_goals(20)),0)
        finally: db.cleanup()
    def test_greeting_with_punctuation_and_wake_name_gets_direct_answer(self):
        db,store,agent,service=self.make()
        try:
            for greeting in ('Hello.','Hello Sparkle.','Hi Sparkle!'):
                out=service.send(greeting)
                self.assertNotIn('goal_id',out['message'])
                self.assertIsNone(store.load_session(out['session_id']).active_goal_id)
            self.assertEqual(agent.last_target,None)
        finally: db.cleanup()

    def test_explicit_task_capture_does_not_route_to_project_search_or_agent(self):
        db,store,agent,service=self.make()
        try:
            cases=(
                ('Add C++ in my task.','C++'),
                ('Add a new task complete C++ programming.','complete C++ programming'),
                ('Add new task task label is learn C++.','learn C++'),
            )
            for command,label in cases:
                out=service.send(command)
                self.assertTrue(out['result']['task_capture'])
                self.assertEqual(out['result']['task_label'],label)
                self.assertEqual(out['message']['text'],f'Added task: {label}.')
                self.assertNotIn('goal_id',out['message'])
            self.assertEqual(agent.last_target,None)
            self.assertEqual(len(store.all_task_runs(20)),len(cases))
        finally: db.cleanup()

    def test_task_list_request_is_read_only_and_does_not_start_new_task(self):
        db,store,agent,service=self.make()
        try:
            first=service.send('Add a new task learn C++')
            second=service.send('Hello Sparkle, check my task list. Mention them.',session_id=first['session_id'])
            self.assertEqual(second['message']['status'],'COMPLETED')
            self.assertIn('learn C++',second['message']['text'])
            self.assertEqual(second['result']['task_list'][0]['title'],'learn C++')
            self.assertIsNone(store.load_session(second['session_id']).active_goal_id)
            self.assertEqual(len(store.all_task_runs(20)),1)
            self.assertEqual(agent.last_target,None)
        finally: db.cleanup()

    def test_accidental_voice_task_chain_is_not_shown_as_a_real_task(self):
        db,store,agent,service=self.make()
        try:
            service.send('Add a new task complete the C++ learning. designers designing CSS course teach me now What are you doing? that thing delete task Delete that created task')
            out=service._task_list(limit=20)
            self.assertEqual(out['task_list'],[])
            self.assertEqual(agent.last_target,None)
        finally: db.cleanup()

    def test_ordinary_conversation_stays_in_history_and_does_not_create_goal(self):
        db,store,agent,service=self.make()
        try:
            out=service.send('Hello, Michael, how are you? ¿Qué?')
            self.assertNotIn('goal_id',out['message'])
            self.assertIsNone(store.load_session(out['session_id']).active_goal_id)
            self.assertEqual(len(store.recent_goals(20)),0)
            messages=store.conversation_messages(out['session_id'],20)
            self.assertEqual([m['role'] for m in messages],['user','assistant'])
            self.assertEqual(agent.last_target,None)
        finally: db.cleanup()

    def test_plain_text_answer_removes_markdown_markers(self):
        self.assertEqual(ConversationService._plain_text('**Hello** {world} `code`'), 'Hello world code')
        self.assertEqual(ConversationService._plain_text('# Heading\n- One\n- Two'), 'Heading\nOne\nTwo')

    def test_generic_execution_request_is_not_a_goal_surface_record(self):
        self.assertFalse(ConversationService._looks_like_goal_request('research Python releases'))
        self.assertTrue(ConversationService._looks_like_goal_request('create a goal to research Python releases'))

    def test_action_request_still_uses_agent(self):
        db,_,_,service=self.make()
        try: self.assertEqual(service.send('research Python releases')['result']['goal_id'],'goal-1')
        finally: db.cleanup()
    def test_active_session_still_answers_knowledge_question_directly(self):
        db,store,agent,service=self.make()
        try:
            first=service.send('research Python releases')
            out=service.send('what is python programming ?',session_id=first['session_id'])
            self.assertIn('high-level',out['message']['text'])
            self.assertNotIn('goal_id',out['message'])
        finally: db.cleanup()

    def test_active_goal_status_still_wins_over_knowledge_heuristic(self):
        db,store,agent,service=self.make()
        try:
            s=service.ensure_session();store.save_setting('unused',{})
            self.assertFalse(service._looks_like_knowledge_question('How is it going?'))
        finally: db.cleanup()

    def test_conversation_context_tracks_intent_focus_and_continuity(self):
        db,store,agent,service=self.make()
        try:
            first=service.send('Teach me Python functions with a practical example.')
            second=service.send('Now give me three exercises.',session_id=first['session_id'])
            context=second['result']['conversation_context']
            self.assertEqual(context['thread_id'],first['session_id'])
            self.assertEqual(context['continuity'],'CONTINUOUS')
            self.assertEqual(context['intent'],'learning')
            self.assertIn('Teach me Python functions',context['thread_focus'])
            self.assertGreaterEqual(context['turn_count'],3)
            self.assertEqual(service.session_summaries(10)[0]['session_id'],first['session_id'])
        finally: db.cleanup()

if __name__=='__main__': unittest.main()
