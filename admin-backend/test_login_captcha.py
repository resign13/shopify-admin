"""Image challenge regressions; all writes inherit the local *_test guard."""
import base64
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import time
import unittest
from unittest.mock import patch
from flask import Flask
from flask.testing import FlaskClient
from PIL import Image
from test_workbench import application, db, seed
from security_core import Security
import login_captcha


class LoginCaptchaTest(unittest.TestCase):
    def setUp(self):
        seed()
        self.security=application.security
        enabled=patch.object(self.security,'captcha_enabled',True);enabled.start();self.addCleanup(enabled.stop)
        code=patch('login_captcha.random_code',return_value='AB7CD');code.start();self.addCleanup(code.stop)
        self.client=self.bare()
        self.headers=self.preheaders(self.client)

    def bare(self):return FlaskClient(application.app,application.app.response_class)

    def preheaders(self,client):
        token=client.get('/api/auth/csrf').json['csrfToken']
        return {'Origin':'http://localhost','X-CSRF-Token':token}

    def challenge(self,client=None):
        response=(client or self.client).get('/api/auth/admin/captcha')
        self.assertEqual(response.status_code,200,response.json)
        self.assertIn('no-store',response.headers['Cache-Control'])
        return response.json

    def login(self,challenge=None,code='AB7CD',password='Workbench-Test-2026',client=None,headers=None):
        body={'email':'admin@gingtto.test','password':password}
        if challenge is not None:body.update(captchaToken=challenge['captchaToken'],captchaCode=code)
        return (client or self.client).post('/api/auth/admin/login',json=body,headers=headers or self.headers)

    def test_image_nonce_case_insensitive_and_single_use(self):
        first=self.challenge();second=self.challenge()
        self.assertNotEqual(first['captchaToken'],second['captchaToken'])
        self.assertNotIn('AB7CD',str(first))
        self.assertNotIn('code',first)
        with Image.open(BytesIO(base64.b64decode(first['image'].split(',')[1]))) as image:
            self.assertEqual(image.format,'PNG');self.assertEqual(image.size,(160,52))
        self.assertEqual(first['expiresIn'],300)
        result=self.login(first,' ab7cd ')
        self.assertEqual(result.status_code,200,result.json)
        self.assertNotIn('token',result.json)
        # A signed ticket is not enough to replay a previously accepted answer.
        current_headers={'Origin':'http://localhost','X-CSRF-Token':result.json['csrfToken'],'X-Auth-Session':result.json['sessionId']}
        self.assertEqual(self.login(first,headers=current_headers).status_code,400)

    def test_missing_wrong_tampered_expired_and_password_failures_create_no_session(self):
        count=lambda:db._fetch_one('SELECT count(*) AS n FROM admin_sessions')['n']
        before=count()
        self.assertEqual(self.login().status_code,400)
        challenge=self.challenge()
        self.assertEqual(self.login(challenge,'XXXXX').status_code,400)
        self.assertEqual(self.login(challenge).status_code,400)
        fresh=self.challenge();bad={**fresh,'captchaToken':fresh['captchaToken'][:-1]+'z'}
        self.assertEqual(self.login(bad).status_code,400)
        with patch('login_captcha.time.time',return_value=time.time()-301):expired=self.challenge()
        self.assertEqual(self.login(expired).status_code,400)
        good=self.challenge()
        self.assertEqual(self.login(good,password='Wrong fixture password').status_code,401)
        self.assertEqual(self.login(good).status_code,400)
        self.assertEqual(count(),before)

    def test_csrf_still_required_and_not_consumed_on_csrf_failure(self):
        challenge=self.challenge()
        self.assertEqual(self.login(challenge,headers={'Origin':'http://localhost'}).status_code,403)
        self.assertEqual(self.login(challenge).status_code,200)

    def test_concurrent_workers_claim_once(self):
        challenge=self.challenge()
        def submit(_):
            client=self.bare();headers=self.preheaders(client)
            return self.login(challenge,client=client,headers=headers).status_code
        with ThreadPoolExecutor(max_workers=2) as workers:statuses=list(workers.map(submit,range(2)))
        self.assertEqual(sorted(statuses),[200,400])

    def test_refresh_quota_and_compatible_disabled_mode(self):
        with patch.dict('os.environ',{'SECURITY_LIMIT_CAPTCHA':'2'}):
            self.challenge();self.challenge()
            limited=self.client.get('/api/auth/admin/captcha')
            self.assertEqual(limited.status_code,429)
            self.assertGreater(int(limited.headers['Retry-After']),0)
        with patch.object(self.security,'captcha_enabled',False):
            self.assertEqual(self.challenge(),{'enabled':False})
            self.assertEqual(self.login().status_code,200)

    def test_only_admin_login_receives_captcha_and_rejects_invalid_input(self):
        with patch.dict('os.environ',{'SECURITY_ADMIN_CAPTCHA_ENABLED':'1'}):
            store=Flask('store-captcha-check');boundary=Security(store,db,'store')
            self.assertFalse(boundary.captcha_enabled)
            self.assertNotIn('/api/auth/admin/captcha',[str(rule) for rule in store.url_map.iter_rules()])
        for value in [None,True,[],{},'x'*600,'invalid.nonsense','非英文.ticket']:
            self.assertFalse(login_captcha.verify(db,self.security.key,value,'AB7CD'))

    def test_valid_challenge_bad_answer_consumes_once_and_future_ticket_is_rejected(self):
        for answer in [None,[],{},True,'AB7CD'*100]:
            challenge=self.challenge()
            self.assertEqual(self.login(challenge,code=answer).status_code,400)
            self.assertEqual(self.login(challenge).status_code,400)
        with patch('login_captcha.time.time',return_value=time.time()+60):future=self.challenge()
        self.assertEqual(self.login(future).status_code,400)


if __name__=='__main__':unittest.main()
