# -*- coding: utf-8 -*-
# MySqlDB.py
# Copyright (C) 2018-2020 KunoiSayami
#
# This module is part of libpy3 and is released under
# the AGPL v3 License: https://www.gnu.org/licenses/agpl-3.0.txt
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
import logging
import time
import traceback
from threading import Lock, Thread
from typing import Dict, NoReturn, Optional, Sequence, T, Tuple

import pymysql.cursors


class _MySqlDB:

	def __init__(
		self,
		host: str,
		user: str,
		password: str,
		db: str,
		charset: str = 'utf8mb4',
		cursorclass = pymysql.cursors.DictCursor,
		autocommit = False
	):
		self.logger = logging.getLogger(__name__)
		self.logger.setLevel(logging.DEBUG)
		self.host = host
		self.user = user
		self.password = password
		self.db = db
		self.charset = charset
		self.cursorclass = cursorclass
		self.execute_lock = Lock()
		self.last_execute_time = 0
		self.exit_request = False
		self.autocommit = autocommit
		self.cursor = None
		self.retries = 3
		self.init_connection()

	def init_connection(self) -> NoReturn:
		self.mysql_connection = pymysql.connect(
			host = self.host,
			user = self.user,
			password = self.password,
			db = self.db,
			charset = self.charset,
			cursorclass = self.cursorclass,
			autocommit = self.autocommit
		)
		self.cursor = self.mysql_connection.cursor()

	def commit(self) -> NoReturn:
		with self.execute_lock:
			self.cursor.close()
			self.mysql_connection.commit()
			self.cursor = self.mysql_connection.cursor()

	def query(self, sql: str, args: Sequence[T] = ()) -> Tuple[Dict[str, T], ...]:
		self.execute(sql, args)
		return self.cursor.fetchall()

	def query1(self, sql: str, args: Sequence[T] = ()) -> Optional[Dict[str, T]]:
		self.execute(sql, args)
		return self.cursor.fetchone()

	def get_retries(self) -> int:
		self.retries -= 1
		return self.retries
	
	def reset_retries(self) -> NoReturn:
		self.retries = 3

	def execute(self, sql: str, args: Sequence[T] = (), many: bool = False) -> NoReturn:
		with self.execute_lock:
			while self.get_retries():
				try:
					(self.cursor.executemany if many else self.cursor.execute)(sql, args)
					break
				except pymysql.err.InterfaceError:
					self.logger.warning('Got interface error, trying restart connection. (Retries: %d)', self.retries)
					self.logger.debug(traceback.format_exc())
					self._force_close()
					self.init_connection()
					self.logger.info('Restart connection successful')
				except pymysql.err.ProgrammingError:
					err = traceback.format_exc().splitlines()[-1]
					if 'Cursor closed' in err:
						self.cursor = self.mysql_connection.cursor()
				except pymysql.err.OperationalError:
					err = traceback.format_exc().splitlines()[-1]
					if '1213, \'Deadlock found' in err:
						self.logger.warning('Got deadlock found error, trying restart connection. (Retries: %d)', self.retries)
						self.logger.debug(traceback.format_exc())
						self._force_close()
						self.init_connection()
						self.logger.info('Restart connection successful')
				finally:
					self.last_execute_time = time.time()
			self.reset_retries()

	def ping(self) -> NoReturn:
		return self.mysql_connection.ping()

	def do_keepalive(self) -> NoReturn:
		Thread(target = self._do_keepalive, daemon = True).start()

	def _do_keepalive(self) -> NoReturn:
		while self._do_keepalive:
			try:
				if time.time() - self.last_execute_time > 300 and not self.exit_request:
					self.ping()
			finally:
				if self.exit_request: return
				for _ in range(0, 5):
					time.sleep(1)
					if self.exit_request: return

	def close(self) -> NoReturn:
		with self.execute_lock:
			self.exit_request = True
			self.cursor.close()
			self.mysql_connection.commit()
			self.mysql_connection.close()
	
	def _call_without_exception(self, target: 'callable', *args, **kwargs) -> NoReturn:
		try:
			target(*args, **kwargs)
		except:
			pass

	def _force_close(self) -> NoReturn:
		self._call_without_exception(self.cursor.close)
		self._call_without_exception(self.mysql_connection.close)


class MySqlDB(_MySqlDB):
	_self = None
	@staticmethod
	def init_instance(
		host: str,
		user: str,
		password: str,
		db: str,
		charset: str = 'utf8mb4',
		cursorclass = pymysql.cursors.DictCursor,
		autocommit = False
	) -> 'MySqlDB':
		MySqlDB._self = MySqlDB(host, user, password, db, charset, cursorclass, autocommit)
		return MySqlDB._self
	
	@staticmethod
	def get_instance() -> 'MySqlDB':
		return MySqlDB._self
