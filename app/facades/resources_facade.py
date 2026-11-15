from flask import current_app
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from ..utils.errors import AWSRefreshDeadlineExceeded, CachedDataExpiredError

class ResourcesFacade:
    def get_resources(self):
        cache = current_app.extensions['resources_cache']
        resources, errors = cache.get_resources(
            current_app.config['AWS_REGION'], current_app.config['AWS_CACHE_TTL'],
            current_app.config['AWS_REFRESH_TIMEOUT'],
            current_app.config['AWS_FAILURE_COOLDOWN'],
            current_app.config['AWS_TASK_TIMEOUT'],
            current_app.config['AWS_MAX_DATA_AGE']
        )
        resources['errors'] = {}
        resources['warnings'] = {}
        for section, error in errors.items():
            freshness = resources.get('freshness', {}).get(section)
            if not isinstance(error, CachedDataExpiredError) and (resources[section] or freshness):
                resources['warnings'][section] = 'Showing previously fetched data. ' + self._error_message(error)
            else:
                resources['errors'][section] = self._error_message(error)
        return resources

    @staticmethod
    def _error_message(error):
        if isinstance(error, CachedDataExpiredError):
            return 'Previously fetched data is too old to display. Reload to check for fresh results.'
        if isinstance(error, AWSRefreshDeadlineExceeded):
            return 'AWS refresh timed out. Please try again after the retry cooldown.'
        if isinstance(error, TimeoutError):
            return 'AWS refresh is taking longer than expected. Reload shortly for updated data.'
        if isinstance(error, (NoCredentialsError, PartialCredentialsError)):
            return 'AWS credentials are missing or incomplete. Check the application credentials.'
        if isinstance(error, ClientError):
            code = error.response.get('Error', {}).get('Code', '')
            if code in {'AccessDenied', 'AccessDeniedException', 'UnauthorizedOperation'}:
                return 'AWS access denied. Check permissions for these resources.'
            if code in {
                'ExpiredToken', 'ExpiredTokenException', 'InvalidClientTokenId',
                'InvalidAccessKeyId', 'AuthFailure', 'SignatureDoesNotMatch',
                'UnrecognizedClientException',
            }:
                return 'AWS credentials are invalid or expired. Update the application credentials.'
        return 'Unable to retrieve these AWS resources. Please try again later.'
