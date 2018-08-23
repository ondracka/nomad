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

"""
This module comprises a set of persistent document classes that hold all user related
data. These are information about users, their uploads and datasets, and the
associations between users and the assets stored in nomad-xt.

..autoclass:: nomad.users.User
..autoclass:: nomad.users.Upload
..autoclass:: nomad.users.DataSet
"""

import sys
from mongoengine import \
    Document, EmailField, StringField, BooleanField, DateTimeField, ListField, \
    DictField, ReferenceField, connect

from nomad import config

# ensure mongo connection
if 'sphinx' not in sys.modules:
    connect(db=config.mongo.users_db, host=config.mongo.host)


class User(Document):
    """ Represents users in the database. """
    email = EmailField(primary=True)
    name = StringField()


class Upload(Document):
    """
    Represents uploads in the databases. Provides persistence access to the files storage,
    and processing system.

    Attributes:
        file_name: Optional user provided upload name
        upload_id: The upload id. Generated by the database.
        in_staging: True if the upload is still in staging and can be edited by the uploader.
        is_private: True if the upload and its derivitaves are only visible to the uploader.
        proc: The :class:`nomad.processing.UploadProc` that holds the processing state.
        created_time: The timestamp this upload was created.
        upload_time: The timestamp when the system realised the upload.
        proc_time: The timestamp when the processing realised finished by the system.
    """

    name = StringField(default=None)

    in_staging = BooleanField(default=True)
    is_private = BooleanField(default=False)

    presigned_url = StringField()
    upload_time = DateTimeField()
    create_time = DateTimeField()

    proc_time = DateTimeField()
    proc = DictField()

    user = ReferenceField(User, required=True)

    meta = {
        'indexes': [
            'proc.upload_hash',
            'user'
        ]
    }

    @property
    def upload_id(self):
        return self.id.__str__()


class DataSet(Document):
    name = StringField()
    description = StringField()
    doi = StringField()

    user = ReferenceField(User)
    calcs = ListField(StringField)

    meta = {
        'indexes': [
            'user',
            'doi',
            'calcs'
        ]
    }