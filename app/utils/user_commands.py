import click
from flask import current_app
from pymongo.errors import DuplicateKeyError, PyMongoError


def register_user_commands(application):
    @application.cli.group('users')
    def users():
        """Manage dashboard accounts stored in MongoDB."""

    def run(operation):
        try:
            return operation(current_app.extensions['users'])
        except DuplicateKeyError:
            raise click.ClickException('User already exists. Use users set-password to change its password.') from None
        except PyMongoError:
            raise click.ClickException('MongoDB is unavailable or not configured. Check connection and database permissions.') from None
        except ValueError as error:
            raise click.ClickException(str(error)) from None

    @users.command('create')
    @click.argument('username')
    def create(username):
        """Create a user; prompt for its password without echoing it."""
        password = click.prompt('Password', hide_input=True, confirmation_prompt=True)
        run(lambda store: store.create(username, password))
        click.echo(f'Created user {username}.')

    @users.command('set-password')
    @click.argument('username')
    def set_password(username):
        """Replace an existing user's password."""
        password = click.prompt('New password', hide_input=True, confirmation_prompt=True)
        if not run(lambda store: store.set_password(username, password)):
            raise click.ClickException('User does not exist.')
        click.echo(f'Updated password for {username}.')

    @users.command('disable')
    @click.argument('username')
    def disable(username):
        """Disable dashboard access for a user."""
        if not run(lambda store: store.set_active(username, False)):
            raise click.ClickException('User does not exist.')
        click.echo(f'Disabled user {username}.')

    @users.command('enable')
    @click.argument('username')
    def enable(username):
        """Enable dashboard access for an existing user."""
        if not run(lambda store: store.set_active(username, True)):
            raise click.ClickException('User does not exist.')
        click.echo(f'Enabled user {username}.')
