import unittest
from unittest.mock import AsyncMock, MagicMock
from xhamster_api.api import Client
from xhamster_api.modules.errors import LoginFailed

class TestLogin(unittest.IsolatedAsyncioTestCase):
    async def test_login_invalid_password_raises_exception(self):
        client = Client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'name': 'authorizedUserModelSync',
                'extras': {'error': {'username': 'Invalid login or password'}},
                'responseData': {'$id': 'c1a902b0-cb96-4098-89f9-2bd0010586aa'},
                'log': []
            }
        ]

        client.core.request = AsyncMock(return_value=mock_response)

        with self.assertRaises(LoginFailed) as ctx:
            await client.login(username="testuser", password="wrongpassword")
        
        self.assertIn("Invalid login or password", str(ctx.exception))

    async def test_login_valid_password_succeeds(self):
        client = Client()
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                'name': 'authorizedUserModelSync',
                'extras': {'result': True, 'redirectURL': 'https://xhamster.com/login', 'userId': 369187246, 'userType': 'user'},
                'responseData': {'$id': 'c1a902b0-cb96-4098-89f9-2bd0010586aa'},
                'log': []
            }
        ]

        client.core.request = AsyncMock(return_value=mock_response)

        account = await client.login(username="testuser", password="correctpassword")
        self.assertIsNotNone(account)

if __name__ == "__main__":
    unittest.main()
