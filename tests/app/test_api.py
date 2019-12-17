# Copyright 2018 Markus Scheidgen
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an"AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from typing import Any
import pytest
import time
import json
import base64
import zipfile
import io
import inspect
from passlib.hash import bcrypt
import datetime
import os.path
from urllib.parse import urlencode

from nomad.app.utils import rfc3339DateTime
from nomad import coe_repo, search, parsing, files, config, utils
from nomad.files import UploadFiles, PublicUploadFiles
from nomad.processing import Upload, Calc, SUCCESS
from nomad.datamodel import UploadWithMetadata, CalcWithMetadata

from tests.conftest import create_auth_headers, clear_elastic
from tests.test_files import example_file, example_file_mainfile, example_file_contents
from tests.test_files import create_staging_upload, create_public_upload, assert_upload_files
from tests.test_coe_repo import assert_coe_upload
from tests.test_search import assert_search_upload
from tests.processing import test_data as test_processing

from tests.app.test_app import BlueprintClient

logger = utils.get_logger(__name__)


@pytest.fixture(scope='function')
def api(client):
    return BlueprintClient(client, '/api')


@pytest.fixture(scope='function')
def test_user_signature_token(api, test_user_auth):
    rv = api.get('/auth/token', headers=test_user_auth)
    assert rv.status_code == 200
    return json.loads(rv.data)['token']


def get_upload_with_metadata(upload: dict) -> UploadWithMetadata:
    """ Create a :class:`UploadWithMetadata` from a API upload json record. """
    return UploadWithMetadata(
        upload_id=upload['upload_id'], calcs=[
            CalcWithMetadata(calc_id=calc['calc_id'], mainfile=calc['mainfile'])
            for calc in upload['calcs']['results']])


class TestInfo:
    def test_info(self, api):
        rv = api.get('/info/')
        data = json.loads(rv.data)
        assert 'codes' in data
        assert 'parsers' in data
        assert len(data['parsers']) >= len(data['codes'])
        assert rv.status_code == 200


class TestAdmin:
    @pytest.mark.timeout(config.tests.default_timeout)
    def test_reset(self, api, admin_user_auth, expandable_postgres, monkeypatch):
        monkeypatch.setattr('nomad.config.services.disable_reset', False)
        rv = api.post('/admin/reset', headers=admin_user_auth)
        assert rv.status_code == 200

    @pytest.mark.timeout(config.tests.default_timeout)
    def test_remove(self, api, admin_user_auth, expandable_postgres, monkeypatch):
        monkeypatch.setattr('nomad.config.services.disable_reset', False)
        rv = api.post('/admin/remove', headers=admin_user_auth)
        assert rv.status_code == 200

    def test_doesnotexist(self, api, admin_user_auth):
        rv = api.post('/admin/doesnotexist', headers=admin_user_auth)
        assert rv.status_code == 404

    def test_only_admin(self, api, test_user_auth):
        rv = api.post('/admin/reset', headers=test_user_auth)
        assert rv.status_code == 401

    def test_disabled(self, api, admin_user_auth, expandable_postgres, monkeypatch):
        monkeypatch.setattr('nomad.config.services.disable_reset', True)
        rv = api.post('/admin/reset', headers=admin_user_auth)
        assert rv.status_code == 400


class TestAuth:
    def test_xtoken_auth(self, api, test_user: coe_repo.User, no_warn):
        rv = api.get('/uploads/', headers={
            'X-Token': test_user.first_name.lower()  # the test users have their firstname as tokens for convinience
        })

        assert rv.status_code == 200

    def test_xtoken_auth_denied(self, api, no_warn, postgres):
        rv = api.get('/uploads/', headers={
            'X-Token': 'invalid'
        })

        assert rv.status_code == 401

    def test_basic_auth(self, api, test_user_auth, no_warn):
        rv = api.get('/uploads/', headers=test_user_auth)
        assert rv.status_code == 200

    def test_basic_auth_denied(self, api, no_warn):
        basic_auth_base64 = base64.b64encode('invalid'.encode('utf-8')).decode('utf-8')
        rv = api.get('/uploads/', headers={
            'Authorization': 'Basic %s' % basic_auth_base64
        })
        assert rv.status_code == 401

    def test_get_user(self, api, test_user_auth, test_user: coe_repo.User, no_warn):
        rv = api.get('/auth/user', headers=test_user_auth)
        assert rv.status_code == 200
        self.assert_user(api, json.loads(rv.data))

    def assert_user(self, api, user):
        for key in ['first_name', 'last_name', 'email', 'token']:
            assert key in user

        rv = api.get('/uploads/', headers={
            'X-Token': user['token']
        })

        assert rv.status_code == 200

    def test_signature_token(self, test_user_signature_token, no_warn):
        assert test_user_signature_token is not None

    @pytest.mark.parametrize('token, affiliation', [
        ('test_token', dict(name='HU Berlin', address='Unter den Linden 6')),
        (None, None)])
    def test_put_user(self, api, postgres, admin_user_auth, token, affiliation):
        data = dict(
            email='test@email.com', last_name='Tester', first_name='Testi',
            token=token, affiliation=affiliation,
            password=bcrypt.encrypt('test_password', ident='2y'))

        data = {key: value for key, value in data.items() if value is not None}

        rv = api.put(
            '/auth/user', headers=admin_user_auth,
            content_type='application/json', data=json.dumps(data))

        assert rv.status_code == 200
        self.assert_user(api, json.loads(rv.data))

    def test_put_user_admin_only(self, api, test_user_auth):
        rv = api.put(
            '/auth/user', headers=test_user_auth,
            content_type='application/json', data=json.dumps(dict(
                email='test@email.com', last_name='Tester', first_name='Testi',
                password=bcrypt.encrypt('test_password', ident='2y'))))
        assert rv.status_code == 401

    def test_put_user_required_field(self, api, admin_user_auth):
        rv = api.put(
            '/auth/user', headers=admin_user_auth,
            content_type='application/json', data=json.dumps(dict(
                email='test@email.com', password=bcrypt.encrypt('test_password', ident='2y'))))
        assert rv.status_code == 400

    def test_post_user(self, api, postgres, admin_user_auth):
        rv = api.put(
            '/auth/user', headers=admin_user_auth,
            content_type='application/json', data=json.dumps(dict(
                email='test@email.com', last_name='Tester', first_name='Testi',
                password=bcrypt.encrypt('test_password', ident='2y'))))

        assert rv.status_code == 200
        user = json.loads(rv.data)

        rv = api.post(
            '/auth/user', headers={'X-Token': user['token']},
            content_type='application/json', data=json.dumps(dict(
                last_name='Tester', first_name='Testi v.',
                password=bcrypt.encrypt('test_password_changed', ident='2y'))))
        assert rv.status_code == 200
        self.assert_user(api, json.loads(rv.data))


class TestUploads:

    def assert_uploads(self, upload_json_str, count=0, **kwargs):
        data = json.loads(upload_json_str)
        assert 'pagination' in data
        assert 'page' in data['pagination']

        data = data['results']
        assert isinstance(data, list)
        assert len(data) == count

        if count > 0:
            self.assert_upload(json.dumps(data[0]), **kwargs)

    def assert_upload(self, upload_json_str, id=None, **kwargs):
        data = json.loads(upload_json_str)
        assert 'upload_id' in data
        if id is not None:
            assert id == data['upload_id']
        assert 'create_time' in data

        for key, value in kwargs.items():
            assert data.get(key, None) == value

        return data

    def assert_processing(self, api, test_user_auth, upload_id):
        upload_endpoint = '/uploads/%s' % upload_id

        # poll until completed
        upload = self.block_until_completed(api, upload_id, test_user_auth)

        assert len(upload['tasks']) == 4
        assert upload['tasks_status'] == SUCCESS
        assert upload['current_task'] == 'cleanup'
        assert not upload['process_running']

        calcs = upload['calcs']['results']
        for calc in calcs:
            assert calc['tasks_status'] == SUCCESS
            assert calc['current_task'] == 'archiving'
            assert len(calc['tasks']) == 3
            assert api.get('/archive/logs/%s/%s' % (calc['upload_id'], calc['calc_id']), headers=test_user_auth).status_code == 200

        if upload['calcs']['pagination']['total'] > 1:
            rv = api.get('%s?page=2&per_page=1&order_by=tasks_status' % upload_endpoint, headers=test_user_auth)
            assert rv.status_code == 200
            upload = self.assert_upload(rv.data)
            assert len(upload['calcs']['results']) == 1

        upload_with_metadata = get_upload_with_metadata(upload)
        assert_upload_files(upload_with_metadata, files.StagingUploadFiles)
        assert_search_upload(upload_with_metadata, additional_keys=['atoms', 'system'])

    def assert_published(self, api, test_user_auth, upload_id, proc_infra, with_coe_repo=True, metadata={}, publish_with_metadata: bool = True):
        rv = api.get('/uploads/%s' % upload_id, headers=test_user_auth)
        upload = self.assert_upload(rv.data)

        upload_with_metadata = get_upload_with_metadata(upload)

        rv = api.post(
            '/uploads/%s' % upload_id,
            headers=test_user_auth,
            data=json.dumps(dict(operation='publish', metadata=metadata if publish_with_metadata else {})),
            content_type='application/json')
        assert rv.status_code == 200
        upload = self.assert_upload(rv.data)
        assert upload['current_process'] == 'publish_upload'
        assert upload['process_running']

        additional_keys = ['with_embargo']
        if publish_with_metadata and 'external_id' in metadata:
            additional_keys.append('external_id')

        if with_coe_repo:
            additional_keys.append('pid')

        self.block_until_completed(api, upload_id, test_user_auth)
        upload_proc = Upload.objects(upload_id=upload_id).first()
        assert upload_proc is not None
        assert upload_proc.published is True

        if with_coe_repo:
            assert_coe_upload(upload_with_metadata.upload_id, user_metadata=metadata)
        assert_upload_files(upload_with_metadata, files.PublicUploadFiles, published=True)
        assert_search_upload(upload_with_metadata, additional_keys=additional_keys, published=True)

    def block_until_completed(self, api, upload_id: str, test_user_auth):
        while True:
            time.sleep(0.1)
            rv = api.get('/uploads/%s' % upload_id, headers=test_user_auth)
            if rv.status_code == 200:
                upload = self.assert_upload(rv.data)
                if not upload['process_running'] and not upload['tasks_running']:
                    return upload
            elif rv.status_code == 404:
                return None
            else:
                raise Exception(
                    'unexpected status code while blocking for upload processing: %s' %
                    str(rv.status_code))

    def assert_upload_does_not_exist(self, api, upload_id: str, test_user_auth):
        self.block_until_completed(api, upload_id, test_user_auth)

        rv = api.get('/uploads/%s' % upload_id, headers=test_user_auth)
        assert rv.status_code == 404
        assert Upload.objects(upload_id=upload_id).first() is None
        assert Calc.objects(upload_id=upload_id).count() is 0
        upload_files = UploadFiles.get(upload_id)
        assert upload_files is None or isinstance(upload_files, PublicUploadFiles)

    def test_get_command(self, api, test_user_auth, no_warn):
        rv = api.get('/uploads/command', headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert 'upload_command' in data
        assert '/api/uploads' in data['upload_command']
        assert 'upload_url' in data

    def test_get_empty(self, api, test_user_auth, no_warn):
        rv = api.get('/uploads/', headers=test_user_auth)

        assert rv.status_code == 200
        self.assert_uploads(rv.data, count=0)

    def test_get_not_existing(self, api, test_user_auth, no_warn):
        rv = api.get('/uploads/123456789012123456789012', headers=test_user_auth)
        assert rv.status_code == 404

    @pytest.mark.parametrize('mode', ['multipart', 'stream', 'local_path'])
    @pytest.mark.parametrize('name', [None, 'test_name'])
    def test_put(self, api, test_user_auth, proc_infra, example_upload, mode, name, no_warn):
        file = example_upload
        if name:
            url = '/uploads/?name=%s' % name
        else:
            url = '/uploads/'

        if mode == 'multipart':
            rv = api.put(
                url, data=dict(file=(open(file, 'rb'), 'the_name')), headers=test_user_auth)
            if not name:
                name = 'the_name'
        elif mode == 'stream':
            with open(file, 'rb') as f:
                rv = api.put(url, data=f.read(), headers=test_user_auth)
        elif mode == 'local_path':
            url += '&' if name else '?'
            url += 'local_path=%s' % file
            rv = api.put(url, headers=test_user_auth)
        else:
            assert False

        assert rv.status_code == 200
        if mode == 'local_path':
            upload = self.assert_upload(rv.data, upload_path=file, name=name)
        else:
            upload = self.assert_upload(rv.data, name=name)
        assert upload['tasks_running']

        self.assert_processing(api, test_user_auth, upload['upload_id'])

    @pytest.mark.timeout(config.tests.default_timeout)
    def test_upload_limit(self, api, mongo, test_user, test_user_auth, proc_infra):
        for _ in range(0, config.services.upload_limit):
            Upload.create(user=test_user)
        file = example_file
        rv = api.put('/uploads/?local_path=%s' % file, headers=test_user_auth)
        assert rv.status_code == 400
        assert Upload.user_uploads(test_user).count() == config.services.upload_limit

    def test_delete_not_existing(self, api, test_user_auth, no_warn):
        rv = api.delete('/uploads/123456789012123456789012', headers=test_user_auth)
        assert rv.status_code == 404

    @pytest.fixture(scope='function')
    def slow_processing(self, monkeypatch):
        old_cleanup = Upload.cleanup

        def slow_cleanup(self):
            time.sleep(0.5)
            old_cleanup(self)

        monkeypatch.setattr('nomad.processing.data.Upload.cleanup', slow_cleanup)
        yield True
        monkeypatch.setattr('nomad.processing.data.Upload.cleanup', old_cleanup)

    def test_delete_published(self, api, test_user_auth, proc_infra, no_warn, with_publish_to_coe_repo):
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        self.assert_published(api, test_user_auth, upload['upload_id'], proc_infra, with_coe_repo=with_publish_to_coe_repo)
        rv = api.delete('/uploads/%s' % upload['upload_id'], headers=test_user_auth)
        assert rv.status_code == 400

    def test_delete(self, api, test_user_auth, proc_infra, no_warn):
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        rv = api.delete('/uploads/%s' % upload['upload_id'], headers=test_user_auth)
        assert rv.status_code == 200
        self.assert_upload_does_not_exist(api, upload['upload_id'], test_user_auth)

    def test_post_empty(self, api, test_user_auth, empty_upload, proc_infra, no_warn):
        rv = api.put('/uploads/?local_path=%s' % empty_upload, headers=test_user_auth)
        assert rv.status_code == 200
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        rv = api.post(
            '/uploads/%s' % upload['upload_id'], headers=test_user_auth,
            data=json.dumps(dict(operation='publish')),
            content_type='application/json')
        assert rv.status_code == 400

    def test_post(self, api, test_user_auth, non_empty_example_upload, proc_infra, no_warn, with_publish_to_coe_repo):
        rv = api.put('/uploads/?local_path=%s' % non_empty_example_upload, headers=test_user_auth)
        assert rv.status_code == 200
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        self.assert_published(api, test_user_auth, upload['upload_id'], proc_infra, with_coe_repo=with_publish_to_coe_repo)

        # still visible
        assert api.get('/uploads/%s' % upload['upload_id'], headers=test_user_auth).status_code == 200
        # still listed with all=True
        rv = api.get('/uploads/?state=all', headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)['results']
        assert len(data) > 0
        assert any(item['upload_id'] == upload['upload_id'] for item in data)
        # not listed with all=False
        rv = api.get('/uploads/', headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)['results']
        assert not any(item['upload_id'] == upload['upload_id'] for item in data)

    def test_post_metadata(
            self, api, proc_infra, admin_user_auth, test_user_auth, test_user,
            other_test_user, no_warn, example_user_metadata):
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        metadata = dict(**example_user_metadata)
        metadata['_upload_time'] = datetime.datetime.utcnow().isoformat()
        self.assert_published(api, admin_user_auth, upload['upload_id'], proc_infra, metadata)

    def test_post_metadata_forbidden(self, api, proc_infra, test_user_auth, no_warn):
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        rv = api.post(
            '/uploads/%s' % upload['upload_id'],
            headers=test_user_auth,
            data=json.dumps(dict(operation='publish', metadata=dict(_pid=256))),
            content_type='application/json')
        assert rv.status_code == 401

    def test_post_metadata_and_republish(
            self, api, proc_infra, admin_user_auth, test_user_auth, test_user,
            other_test_user, no_warn, example_user_metadata):
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
        upload = self.assert_upload(rv.data)
        self.assert_processing(api, test_user_auth, upload['upload_id'])
        metadata = dict(**example_user_metadata)
        metadata['_upload_time'] = datetime.datetime.utcnow().isoformat()
        self.assert_published(api, admin_user_auth, upload['upload_id'], proc_infra, metadata)
        self.assert_published(api, admin_user_auth, upload['upload_id'], proc_infra, metadata, publish_with_metadata=False)

    def test_post_re_process(self, api, published, test_user_auth, monkeypatch):
        monkeypatch.setattr('nomad.config.version', 're_process_test_version')
        monkeypatch.setattr('nomad.config.commit', 're_process_test_commit')

        upload_id = published.upload_id
        rv = api.post(
            '/uploads/%s' % upload_id,
            headers=test_user_auth,
            data=json.dumps(dict(operation='re-process')),
            content_type='application/json')

        assert rv.status_code == 200
        assert self.block_until_completed(api, upload_id, test_user_auth) is not None

    # TODO validate metadata (or all input models in API for that matter)
    # def test_post_bad_metadata(self, api, proc_infra, test_user_auth, postgres):
    #     rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)
    #     upload = self.assert_upload(rv.data)
    #     self.assert_processing(api, test_user_auth, upload['upload_id'])
    #     rv = api.post(
    #         '/uploads/%s' % upload['upload_id'],
    #         headers=test_user_auth,
    #         data=json.dumps(dict(operation='publish', metadata=dict(doesnotexist='hi'))),
    #         content_type='application/json')
    #     assert rv.status_code == 400

    @pytest.mark.parametrize('upload_file, ending', [
        ('examples_potcar.zip', ''),
        ('examples_potcar_gz.tgz', '.gz')])
    def test_potcar(self, api, proc_infra, test_user_auth, upload_file, ending):
        # only the owner, shared with people are supposed to download the original potcar file
        example_file = 'tests/data/proc/%s' % upload_file
        rv = api.put('/uploads/?local_path=%s' % example_file, headers=test_user_auth)

        upload = self.assert_upload(rv.data)
        upload_id = upload['upload_id']
        self.assert_processing(api, test_user_auth, upload_id)
        self.assert_published(api, test_user_auth, upload_id, proc_infra, with_coe_repo=True)
        rv = api.get('/raw/%s/examples_potcar/POTCAR%s' % (upload_id, ending))
        assert rv.status_code == 401
        rv = api.get('/raw/%s/examples_potcar/POTCAR%s' % (upload_id, ending), headers=test_user_auth)
        assert rv.status_code == 200
        rv = api.get('/raw/%s/examples_potcar/POTCAR%s.stripped' % (upload_id, ending))
        assert rv.status_code == 200


today = datetime.datetime.utcnow().date()


class UploadFilesBasedTests:

    @staticmethod
    def fix_signature(func, wrapper):
        additional_args = list(inspect.signature(func).parameters.values())[4:]
        wrapper_sig = inspect.signature(wrapper)
        wrapper_args = list(wrapper_sig.parameters.values())[:3] + additional_args
        wrapper_sig = wrapper_sig.replace(parameters=tuple(wrapper_args))
        wrapper.__signature__ = wrapper_sig

    @staticmethod
    def check_authorization(func):
        @pytest.mark.parametrize('test_data', [
            [True, None, True],     # in staging for upload
            [True, None, False],    # in staging for different user
            [True, None, None],     # in staging for guest
            [False, True, True],    # in public, restricted for uploader
            [False, True, False],   # in public, restricted for different user
            [False, True, None],    # in public, restricted for guest
            [False, False, True],   # in public, public, for uploader
            [False, False, False],  # in public, public, for different user
            [False, False, None]    # in public, public, for guest
        ], indirect=True)
        def wrapper(self, api, test_data, *args, **kwargs):
            upload, authorized, auth_headers = test_data
            try:
                func(self, api, upload, auth_headers, *args, **kwargs)
            except AssertionError as assertion:
                assertion_str = str(assertion)
                if not authorized:
                    if '0 == 5' in assertion_str:
                        # the user is not authorized an gets an empty zip as expected
                        return
                    if '401' in assertion_str:
                        # the user is not authorized and gets a 401 as expected
                        return
                raise assertion

            if not authorized:
                assert False
        UploadFilesBasedTests.fix_signature(func, wrapper)
        return wrapper

    @staticmethod
    def ignore_authorization(func):
        @pytest.mark.parametrize('test_data', [
            [True, None, True],      # in staging
            [False, False, None],    # in public
        ], indirect=True)
        def wrapper(self, api, test_data, *args, **kwargs):
            upload, _, auth_headers = test_data
            func(self, api, upload, auth_headers, *args, **kwargs)
        UploadFilesBasedTests.fix_signature(func, wrapper)
        return wrapper

    @pytest.fixture(scope='function')
    def test_data(self, request, postgres, mongo, raw_files, no_warn, test_user, other_test_user):
        # delete potential old test files
        for _ in [0, 1]:
            upload_files = UploadFiles.get('test_upload')
            if upload_files:
                upload_files.delete()

        in_staging, restricted, for_uploader = request.param

        if in_staging:
            authorized = for_uploader
        else:
            authorized = not restricted or for_uploader

        if for_uploader:
            auth_headers = create_auth_headers(test_user)
        elif for_uploader is False:
            auth_headers = create_auth_headers(other_test_user)
        else:
            auth_headers = None

        calc_specs = 'r' if restricted else 'p'
        if in_staging:
            Upload.create(user=test_user, upload_id='test_upload')
            _, upload_files = create_staging_upload('test_upload', calc_specs=calc_specs)
        else:
            _, upload_files = create_public_upload('test_upload', calc_specs=calc_specs)
            postgres.begin()
            coe_upload = coe_repo.Upload(
                upload_name='test_upload',
                user_id=test_user.user_id, is_processed=True)
            postgres.add(coe_upload)
            postgres.commit()

        yield 'test_upload', authorized, auth_headers

        upload_files.delete()


class TestArchive(UploadFilesBasedTests):
    @UploadFilesBasedTests.check_authorization
    def test_get(self, api, upload, auth_headers):
        rv = api.get('/archive/%s/0' % upload, headers=auth_headers)
        assert rv.status_code == 200
        assert json.loads(rv.data) is not None

    @UploadFilesBasedTests.ignore_authorization
    def test_get_signed(self, api, upload, _, test_user_signature_token):
        rv = api.get('/archive/%s/0?token=%s' % (upload, test_user_signature_token))
        assert rv.status_code == 200
        assert json.loads(rv.data) is not None

    @UploadFilesBasedTests.check_authorization
    def test_get_calc_proc_log(self, api, upload, auth_headers):
        rv = api.get('/archive/logs/%s/0' % upload, headers=auth_headers)
        assert rv.status_code == 200
        assert len(rv.data) > 0

    @UploadFilesBasedTests.ignore_authorization
    def test_get_calc_proc_log_signed(self, api, upload, _, test_user_signature_token):
        rv = api.get('/archive/logs/%s/0?token=%s' % (upload, test_user_signature_token))
        assert rv.status_code == 200
        assert len(rv.data) > 0

    @UploadFilesBasedTests.ignore_authorization
    def test_get_non_existing_archive(self, api, upload, auth_headers):
        rv = api.get('/archive/%s' % 'doesnt/exist', headers=auth_headers)
        assert rv.status_code == 404

    @pytest.mark.parametrize('info', [
        'all.nomadmetainfo.json',
        'all.experimental.nomadmetainfo.json',
        'vasp.nomadmetainfo.json',
        'mpes.nomadmetainfo.json'])
    def test_get_metainfo(self, api, info):
        rv = api.get('/archive/metainfo/%s' % info)
        assert rv.status_code == 200
        metainfo = json.loads((rv.data))
        assert len(metainfo) > 0


class TestRepo():
    @pytest.fixture(scope='class')
    def example_elastic_calcs(
            self, elastic_infra, normalized: parsing.LocalBackend,
            test_user: coe_repo.User, other_test_user: coe_repo.User):
        clear_elastic(elastic_infra)

        calc_with_metadata = CalcWithMetadata(upload_id=0, calc_id=0, upload_time=today)
        calc_with_metadata.files = ['test/mainfile.txt']
        calc_with_metadata.apply_domain_metadata(normalized)

        calc_with_metadata.update(datasets=[
            utils.POPO(id='ds_id', doi=dict(value='ds_doi'), name='ds_name')])

        calc_with_metadata.update(
            calc_id='1', uploader=test_user.to_popo(), published=True, with_embargo=False)
        search.Entry.from_calc_with_metadata(calc_with_metadata).save(refresh=True)

        calc_with_metadata.update(
            calc_id='2', uploader=other_test_user.to_popo(), published=True,
            with_embargo=False, pid=2, upload_time=today - datetime.timedelta(days=5), external_id='external_2')
        calc_with_metadata.update(
            atoms=['Fe'], comment='this is a specific word', formula='AAA', basis_set='zzz')
        search.Entry.from_calc_with_metadata(calc_with_metadata).save(refresh=True)

        calc_with_metadata.update(
            calc_id='3', uploader=other_test_user.to_popo(), published=False,
            with_embargo=False, pid=3, external_id='external_3')
        search.Entry.from_calc_with_metadata(calc_with_metadata).save(refresh=True)

        calc_with_metadata.update(
            calc_id='4', uploader=other_test_user.to_popo(), published=True,
            with_embargo=True, pid=4, external_id='external_4')
        search.Entry.from_calc_with_metadata(calc_with_metadata).save(refresh=True)

    def assert_search(self, rv: Any, number_of_calcs: int) -> dict:
        if rv.status_code != 200:
            print(rv.data)
        assert rv.status_code == 200

        data = json.loads(rv.data)

        results = data.get('results', None)
        assert results is not None
        assert isinstance(results, list)
        assert len(results) == number_of_calcs

        return data

    def test_own_calc(self, api, example_elastic_calcs, no_warn, test_user_auth):
        rv = api.get('/repo/0/1', headers=test_user_auth)
        assert rv.status_code == 200

    def test_public_calc(self, api, example_elastic_calcs, no_warn, other_test_user_auth):
        rv = api.get('/repo/0/1', headers=other_test_user_auth)
        assert rv.status_code == 200

    def test_embargo_calc(self, api, example_elastic_calcs, no_warn, test_user_auth):
        rv = api.get('/repo/0/4', headers=test_user_auth)
        assert rv.status_code == 401

    def test_own_embargo_calc(self, api, example_elastic_calcs, no_warn, other_test_user_auth):
        rv = api.get('/repo/0/4', headers=other_test_user_auth)
        assert rv.status_code == 200

    def test_staging_calc(self, api, example_elastic_calcs, no_warn, test_user_auth):
        rv = api.get('/repo/0/3', headers=test_user_auth)
        assert rv.status_code == 401

    def test_own_staging_calc(self, api, example_elastic_calcs, no_warn, other_test_user_auth):
        rv = api.get('/repo/0/3', headers=other_test_user_auth)
        assert rv.status_code == 200

    def test_non_existing_calcs(self, api, example_elastic_calcs, test_user_auth):
        rv = api.get('/repo/0/10', headers=test_user_auth)
        assert rv.status_code == 404

    def test_search_datasets(self, api, example_elastic_calcs, no_warn, other_test_user_auth):
        rv = api.get('/repo/?owner=all&datasets=true', headers=other_test_user_auth)
        data = self.assert_search(rv, 4)

        datasets = data.get('datasets', None)
        assert datasets is not None
        values = datasets['values']
        assert values['ds_id']['total'] == 4
        assert values['ds_id']['examples'][0]['datasets'][0]['id'] == 'ds_id'
        assert 'after' in datasets

    @pytest.mark.parametrize('calcs, owner, auth', [
        (2, 'all', 'none'),
        (2, 'all', 'test_user'),
        (4, 'all', 'other_test_user'),
        (1, 'user', 'test_user'),
        (3, 'user', 'other_test_user'),
        (0, 'staging', 'test_user'),
        (1, 'staging', 'other_test_user')
    ])
    def test_search_owner(self, api, example_elastic_calcs, no_warn, test_user_auth, other_test_user_auth, calcs, owner, auth):
        auth = dict(none=None, test_user=test_user_auth, other_test_user=other_test_user_auth).get(auth)
        rv = api.get('/repo/?owner=%s' % owner, headers=auth)
        data = self.assert_search(rv, calcs)
        results = data.get('results', None)
        if calcs > 0:
            for key in ['uploader', 'calc_id', 'formula', 'upload_id']:
                assert key in results[0]

    @pytest.mark.parametrize('calcs, start, end', [
        (2, today - datetime.timedelta(days=6), today),
        (2, today - datetime.timedelta(days=5), today),
        (1, today - datetime.timedelta(days=4), today),
        (1, today, today),
        (1, today - datetime.timedelta(days=6), today - datetime.timedelta(days=5)),
        (0, today - datetime.timedelta(days=7), today - datetime.timedelta(days=6)),
        (2, None, None),
        (1, today, None),
        (2, None, today)
    ])
    def test_search_time(self, api, example_elastic_calcs, no_warn, calcs, start, end):
        query_string = ''
        if start is not None:
            query_string = 'from_time=%s' % rfc3339DateTime.format(start)
        if end is not None:
            if query_string != '':
                query_string += '&'
            query_string += 'until_time=%s' % rfc3339DateTime.format(end)
        if query_string != '':
            query_string = '?%s' % query_string

        rv = api.get('/repo/%s' % query_string)
        self.assert_search(rv, calcs)

    @pytest.mark.parametrize('calcs, quantity, value, user', [
        (2, 'system', 'bulk', 'test_user'),
        (0, 'system', 'atom', 'test_user'),
        (1, 'atoms', 'Br', 'test_user'),
        (1, 'atoms', 'Fe', 'test_user'),
        (0, 'atoms', ['Fe', 'Br', 'A', 'B'], 'test_user'),
        (0, 'only_atoms', ['Br', 'Si'], 'test_user'),
        (1, 'only_atoms', ['Fe'], 'test_user'),
        (1, 'only_atoms', ['Br', 'K', 'Si'], 'test_user'),
        (1, 'only_atoms', ['Br', 'Si', 'K'], 'test_user'),
        (1, 'comment', 'specific', 'test_user'),
        (1, 'authors', 'Hofstadter, Leonard', 'test_user'),
        (2, 'files', 'test/mainfile.txt', 'test_user'),
        (2, 'paths', 'mainfile.txt', 'test_user'),
        (2, 'paths', 'test', 'test_user'),
        (2, 'quantities', ['wyckoff_letters_primitive', 'hall_number'], 'test_user'),
        (0, 'quantities', 'dos', 'test_user'),
        (2, 'external_id', 'external_2,external_3', 'other_test_user'),
        (1, 'external_id', 'external_2', 'test_user'),
        (1, 'external_id', 'external_2,external_3', 'test_user'),
        (0, 'external_id', 'external_x', 'test_user')
    ])
    def test_search_parameters(
            self, api, example_elastic_calcs, no_warn, test_user_auth,
            other_test_user_auth, calcs, quantity, value, user):
        user_auth = test_user_auth if user == 'test_user' else other_test_user_auth
        query_string = urlencode({quantity: value, 'statistics': True}, doseq=True)

        rv = api.get('/repo/?%s' % query_string, headers=user_auth)
        logger.debug('run search quantities test', query_string=query_string)
        data = self.assert_search(rv, calcs)

        statistics = data.get('statistics', None)
        assert statistics is not None
        if quantity == 'system' and calcs != 0:
            # for simplicity we only assert on quantities for this case
            assert 'system' in statistics
            assert len(statistics['system']) == 1
            assert value in statistics['system']

    metrics_permutations = [[], search.metrics_names] + [[metric] for metric in search.metrics_names]

    def test_search_admin(self, api, example_elastic_calcs, no_warn, admin_user_auth):
        rv = api.get('/repo/?owner=admin', headers=admin_user_auth)
        self.assert_search(rv, 4)

    def test_search_admin_auth(self, api, example_elastic_calcs, no_warn, test_user_auth):
        rv = api.get('/repo/?owner=admin', headers=test_user_auth)
        assert rv.status_code == 401

        rv = api.get('/repo/?owner=admin')
        assert rv.status_code == 401

    @pytest.mark.parametrize('metrics', metrics_permutations)
    def test_search_total_metrics(self, api, example_elastic_calcs, no_warn, metrics):
        rv = api.get('/repo/?%s' % urlencode(dict(metrics=metrics, statistics=True, datasets=True), doseq=True))
        assert rv.status_code == 200, str(rv.data)
        data = json.loads(rv.data)
        total_metrics = data.get('statistics', {}).get('total', {}).get('all', None)
        assert total_metrics is not None
        assert 'code_runs' in total_metrics
        for metric in metrics:
            assert metric in total_metrics

    @pytest.mark.parametrize('metrics', metrics_permutations)
    def test_search_aggregation_metrics(self, api, example_elastic_calcs, no_warn, metrics):
        rv = api.get('/repo/?%s' % urlencode(dict(metrics=metrics, statistics=True, datasets=True), doseq=True))
        assert rv.status_code == 200
        data = json.loads(rv.data)
        for name, quantity in data.get('statistics').items():
            for metrics_result in quantity.values():
                assert 'code_runs' in metrics_result
                if name != 'authors':
                    for metric in metrics:
                        assert metric in metrics_result
                else:
                    assert len(metrics_result) == 1  # code_runs is the only metric for authors

    def test_search_date_histogram(self, api, example_elastic_calcs, no_warn):
        rv = api.get('/repo/?date_histogram=true&metrics=total_energies')
        assert rv.status_code == 200
        data = json.loads(rv.data)
        histogram = data.get('statistics').get('date_histogram')
        assert len(histogram) > 0

    @pytest.mark.parametrize('n_results, page, per_page', [(2, 1, 5), (1, 1, 1), (0, 2, 3)])
    def test_search_pagination(self, api, example_elastic_calcs, no_warn, n_results, page, per_page):
        rv = api.get('/repo/?page=%d&per_page=%d&statistics=true' % (page, per_page))
        assert rv.status_code == 200
        data = json.loads(rv.data)
        results = data.get('results', None)
        assert data['pagination']['total'] == 2
        assert results is not None
        assert len(results) == n_results

    @pytest.mark.parametrize('first, order_by, order', [
        ('1', 'formula', -1), ('2', 'formula', 1),
        ('2', 'basis_set', -1), ('1', 'basis_set', 1),
        (None, 'authors', -1)])
    def test_search_order(self, api, example_elastic_calcs, no_warn, first, order_by, order):
        rv = api.get('/repo/?order_by=%s&order=%d' % (order_by, order))
        assert rv.status_code == 200
        data = json.loads(rv.data)
        results = data.get('results', None)
        assert data['pagination']['total'] == 2
        assert len(results) == 2
        if first is not None:
            assert results[0]['calc_id'] == first

    @pytest.mark.parametrize('n_results, size', [(2, None), (2, 5), (1, 1)])
    def test_search_scroll(self, api, example_elastic_calcs, no_warn, n_results, size):
        if size is not None:
            rv = api.get('/repo/?scroll=1,&per_page=%d' % size)
        else:
            rv = api.get('/repo/?scroll=1')

        assert rv.status_code == 200
        data = json.loads(rv.data)
        results = data.get('results', None)
        assert data.get('scroll', {}).get('size', -1) > 0
        assert results is not None
        assert len(results) == n_results
        scroll_id = data.get('scroll', {}).get('scroll_id', None)
        assert scroll_id is not None

        has_another_page = False
        while scroll_id is not None:
            rv = api.get('/repo/?scroll=1&scroll_id=%s' % scroll_id)
            data = json.loads(rv.data)
            scroll_id = data.get('scroll', {}).get('scroll_id', None)
            has_another_page |= len(data.get('results')) > 0

        if n_results < 2:
            assert has_another_page

    def test_search_user_authrequired(self, api, example_elastic_calcs, no_warn):
        rv = api.get('/repo/?owner=user')
        assert rv.status_code == 401

    @pytest.mark.parametrize('calcs, quantity, value', [
        (2, 'system', 'bulk'),
        (0, 'system', 'atom'),
        (1, 'atoms', 'Br'),
        (1, 'atoms', 'Fe'),
        (1, 'authors', 'Hofstadter, Leonard'),
        (2, 'files', 'test/mainfile.txt'),
        (0, 'quantities', 'dos')
    ])
    def test_quantity_search(self, api, example_elastic_calcs, no_warn, test_user_auth, calcs, quantity, value):
        rv = api.get('/repo/%s' % quantity, headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)
        values = data['quantity']['values']
        assert (value in values) == (calcs > 0)
        if value in values:
            assert values[value]['total'] == calcs
        else:
            assert 0 == calcs

    def test_quantity_search_after(self, api, example_elastic_calcs, no_warn, test_user_auth):
        rv = api.get('/repo/atoms?size=1')
        assert rv.status_code == 200
        data = json.loads(rv.data)

        quantity = data['quantity']
        assert 'after' in quantity
        after = quantity['after']
        assert len(quantity['values']) == 1
        value = list(quantity['values'].keys())[0]

        while True:
            rv = api.get('/repo/atoms?size=1&after=%s' % after)
            assert rv.status_code == 200
            data = json.loads(rv.data)

            quantity = data['quantity']

            if quantity.get('after') is None:
                assert len(quantity['values']) == 0
                break
            assert len(quantity['values']) == 1
            assert value != list(quantity['values'].keys())[0]
            assert after != quantity['after']
            after = quantity['after']

    @pytest.mark.parametrize('pid, with_login, success', [
        (2, True, True), (2, False, True),
        (3, True, True), (3, False, False),
        (4, True, True), (4, False, False)])
    def test_resolve_pid(
            self, api, example_elastic_calcs, other_test_user_auth, pid, with_login,
            success, no_warn):
        rv = api.get(
            '/repo/pid/%d' % pid,
            headers=other_test_user_auth if with_login else {})
        assert rv.status_code == 200 if success else 404
        if success:
            assert json.loads(rv.data)['calc_id'] == '%d' % pid
            assert json.loads(rv.data)['upload_id'] == '0'

    @pytest.mark.timeout(config.tests.default_timeout)
    def test_raw_id(self, api, test_user, test_user_auth, proc_infra):
        example_upload_file = 'tests/data/proc/with_raw_id.zip'
        example_upload_id = os.path.basename(example_upload_file).replace('.zip', '')
        test_processing.run_processing((example_upload_id, example_upload_file), test_user)

        rv = api.get(
            '/repo/?%s' % urlencode(dict(owner='all', raw_id='C61A2F88-A0EA-4F0B-AA47-A715868B2E26')),
            headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['pagination']['total'] == 1
        assert data['results'][0]['raw_id'] == 'C61A2F88-A0EA-4F0B-AA47-A715868B2E26'

    def test_optimade(self, api, non_empty_processed, test_user_auth):
        rv = api.get(
            '/repo/?%s' % urlencode(dict(owner='all', optimade='nelements >= 1')),
            headers=test_user_auth)
        assert rv.status_code == 200
        data = json.loads(rv.data)
        assert data['pagination']['total'] > 0


class TestRaw(UploadFilesBasedTests):

    def assert_zip_file(self, rv, files: int = -1, basename: bool = None):
        assert rv.status_code == 200
        assert len(rv.data) > 0
        with zipfile.ZipFile(io.BytesIO(rv.data)) as zip_file:
            assert zip_file.testzip() is None
            zip_files = zip_file.namelist()
            if files >= 0:
                assert len(zip_files) == files
            if basename is not None:
                if basename:
                    assert all(
                        os.path.basename(name) == name
                        for name in zip_files if name != 'manifest.json')
                else:
                    assert all(
                        os.path.basename(name) != name
                        for name in zip_files for name in zip_files if name != 'manifest.json')

    def test_raw_file_from_calc(self, api, non_empty_processed, test_user_auth):
        calc = list(non_empty_processed.calcs)[0]
        url = '/raw/calc/%s/%s/%s' % (
            non_empty_processed.upload_id, calc.calc_id, os.path.basename(calc.mainfile))
        rv = api.get(url, headers=test_user_auth)
        assert rv.status_code == 200
        assert len(rv.data) > 0

        url = '/raw/calc/%s/%s/' % (non_empty_processed.upload_id, calc.calc_id)
        rv = api.get(url, headers=test_user_auth)
        assert rv.status_code == 200
        result = json.loads(rv.data)
        assert len(result['contents']) > 0

    @UploadFilesBasedTests.check_authorization
    def test_raw_file(self, api, upload, auth_headers):
        url = '/raw/%s/%s' % (upload, example_file_mainfile)
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 200
        assert len(rv.data) > 0

    @UploadFilesBasedTests.check_authorization
    def test_raw_file_partial(self, api, upload, auth_headers):
        url = '/raw/%s/%s?offset=0&length=20' % (upload, example_file_mainfile)
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 200
        start_data = rv.data
        assert len(start_data) == 20

        url = '/raw/%s/%s?offset=10&length=10' % (upload, example_file_mainfile)
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 200
        next_data = rv.data
        assert len(rv.data) == 10
        assert start_data[10:] == next_data

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_file_signed(self, api, upload, _, test_user_signature_token):
        url = '/raw/%s/%s?token=%s' % (upload, example_file_mainfile, test_user_signature_token)
        rv = api.get(url)
        assert rv.status_code == 200
        assert len(rv.data) > 0

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_file_missing_file(self, api, upload, auth_headers):
        url = '/raw/%s/does/not/exist' % upload
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 404
        data = json.loads(rv.data)
        assert 'files' not in data

    @pytest.mark.parametrize('compress', [True, False])
    @UploadFilesBasedTests.ignore_authorization
    def test_raw_file_wildcard(self, api, upload, auth_headers, compress):
        url = '/raw/%s/examples*' % upload
        if compress:
            url = '%s?compress=1' % url
        rv = api.get(url, headers=auth_headers)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents))

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_file_wildcard_missing(self, api, upload, auth_headers):
        url = '/raw/%s/does/not/exist*' % upload
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 404

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_file_missing_upload(self, api, upload, auth_headers):
        url = '/raw/doesnotexist/%s' % example_file_mainfile
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 404

    @pytest.mark.parametrize('compress, strip', [(True, False), (False, False), (False, True)])
    @UploadFilesBasedTests.check_authorization
    def test_raw_files(self, api, upload, auth_headers, compress, strip):
        url = '/raw/%s?files=%s' % (
            upload, ','.join(example_file_contents))
        if compress:
            url = '%s&compress=1' % url
        if strip:
            url = '%s&strip=1' % url
        rv = api.get(url, headers=auth_headers)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents), basename=strip)

    @pytest.mark.parametrize('compress', [False, True])
    def test_raw_files_from_query_upload_id(self, api, non_empty_processed, test_user_auth, compress):
        url = '/raw/query?upload_id=%s&compress=%s' % (non_empty_processed.upload_id, 'true' if compress else 'false')
        rv = api.get(url, headers=test_user_auth)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents) + 1)

    @pytest.mark.parametrize('query_params', [
        {'atoms': 'Si'},
        {'authors': 'Cooper, Sheldon'}
    ])
    def test_raw_files_from_query(self, api, processeds, test_user_auth, query_params):

        url = '/raw/query?%s' % urlencode(query_params)
        rv = api.get(url, headers=test_user_auth)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents) * len(processeds) + 1)
        with zipfile.ZipFile(io.BytesIO(rv.data)) as zip_file:
            with zip_file.open('manifest.json', 'r') as f:
                manifest = json.load(f)
                assert len(manifest) == len(processeds)

    def test_raw_files_from_empty_query(self, api, elastic):
        url = '/raw/query?upload_id=doesNotExist'
        rv = api.get(url)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=1)

    @pytest.mark.parametrize('files, pattern, strip', [
        (1, '*.json', False),
        (1, '*.json', True),
        (5, ['*.json', '*.aux'], False)])
    def test_raw_query_pattern(self, api, non_empty_processed, test_user_auth, files, pattern, strip):
        params = dict(file_pattern=pattern)
        if strip:
            params.update(strip=True)
        url = '/raw/query?%s' % urlencode(params, doseq=True)
        rv = api.get(url, headers=test_user_auth)
        assert rv.status_code == 200
        self.assert_zip_file(rv, files=(files + 1), basename=strip)

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_files_signed(self, api, upload, _, test_user_signature_token):
        url = '/raw/%s?files=%s&token=%s' % (
            upload, ','.join(example_file_contents), test_user_signature_token)
        rv = api.get(url)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents))

    @pytest.mark.parametrize('compress', [True, False, None])
    @UploadFilesBasedTests.check_authorization
    def test_raw_files_post(self, api, upload, auth_headers, compress):
        url = '/raw/%s' % upload
        data = dict(files=example_file_contents)
        if compress is not None:
            data.update(compress=compress)
        rv = api.post(url, data=json.dumps(data), content_type='application/json', headers=auth_headers)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=len(example_file_contents))

    @pytest.mark.parametrize('compress', [True, False])
    @UploadFilesBasedTests.ignore_authorization
    def test_raw_files_missing_file(self, api, upload, auth_headers, compress):
        url = '/raw/%s?files=%s,missing/file.txt' % (upload, example_file_mainfile)
        if compress:
            url = '%s&compress=1' % url
        rv = api.get(url, headers=auth_headers)

        assert rv.status_code == 200
        self.assert_zip_file(rv, files=1)

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_files_missing_upload(self, api, upload, auth_headers):
        url = '/raw/doesnotexist?files=shoud/not/matter.txt'
        rv = api.get(url, headers=auth_headers)

        assert rv.status_code == 404

    @pytest.mark.parametrize('path', ['examples_template', 'examples_template/'])
    @UploadFilesBasedTests.ignore_authorization
    def test_raw_files_list(self, api, upload, auth_headers, path):
        url = '/raw/%s/%s' % (upload, path)
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 200
        data = json.loads(rv.data)

        assert len(data['contents']) == 5
        assert data['upload_id'] == upload
        assert data['directory'] == 'examples_template'
        for content in data['contents']:
            assert content['name'] is not None
            assert content['size'] >= 0
        assert '1.aux' in list(content['name'] for content in data['contents'])

    @UploadFilesBasedTests.ignore_authorization
    def test_raw_files_list_missing(self, api, upload, auth_headers):
        url = '/raw/%s/examples_' % upload
        rv = api.get(url, headers=auth_headers)
        assert rv.status_code == 404


class TestMirror:

    def test_upload(self, api, published, admin_user_auth, no_warn):
        url = '/mirror/%s' % published.upload_id
        rv = api.get(url, headers=admin_user_auth)
        assert rv.status_code == 200

        data = json.loads(rv.data)
        assert data['upload_id'] == published.upload_id
        assert json.loads(data['upload'])['_id'] == published.upload_id
        assert Upload.from_json(data['upload']).upload_id == published.upload_id
        assert len(data['calcs']) == len(published.calcs)
        assert data['upload_files_path'] == published.upload_files.os_path

    def test_uploads(self, api, published, admin_user_auth, no_warn):
        rv = api.post(
            '/mirror/',
            content_type='application/json', data='{"query":{}}', headers=admin_user_auth)
        assert rv.status_code == 200, rv.data

        data = json.loads(rv.data)
        assert data[0]['upload_id'] == published.upload_id