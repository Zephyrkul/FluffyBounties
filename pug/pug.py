from typing import Dict, Literal, Union

import discord
from redbot.core import Config, checks, commands
from redbot.core.bot import Red

from .objects import *


def pug_check(func=None, /, *, running: bool = False):
    def predicate(ctx):
        if not isinstance(ctx.cog, PUG):
            return True
        if not ctx.guild:
            return commands.NoPrivateMessage()
        if (ctx.channel.category_id in ctx.cog.lobbies) == running:
            return True
        if running:
            raise commands.UserFeedbackCheckFailure(
                "No PUG is currently running in this category."
            )
        raise commands.UserFeedbackCheckFailure("A PUG is already running in this category.")

    if func is None:
        return commands.check(predicate)
    return commands.check(predicate)(func)


class PUG(commands.Cog):
    """
    COMMANDS:
    start pug, bot posts a message to react to join

    join pug

    stop pug staging, teams are generated

    stop pug session
    """

    def __init__(self, bot: Red):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=2113674295, force_registration=True)
        self.config.register_guild(team_voice=False, team_text=False, archive=None)
        self.lobbies: Dict[int, Lobby] = {}
        self.react_to_join: Dict[int, Lobby] = {}

    async def red_get_data_for_user(self, *, user_id):
        return {}  # we don't store user data

    async def red_delete_data_for_user(self, *, requester, user_id):
        pass  # we don't store user data

    @commands.group()
    @commands.guild_only()
    @checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def pug(self, ctx: commands.Context):
        """
        Create and manage a PUG.

        Mods and up will be able to `[p]pug start` a PUG in a category.
        This creates a Staging group.
        Members can join this group via reaction or command.

        Once mods are set, they can then `[p]pug split` into teams.
        Members can still join to fill up any missing spots.

        Once the PUG is over, mods can `[p]pug stop` an ongoing PUG.
        The bot will clean up and (optionally) archive the PUG.
        """

    @pug.command()
    @checks.mod_or_permissions(manage_channels=True)
    @pug_check(running=False)
    async def start(self, ctx: commands.Context, *, category: discord.CategoryChannel = None):
        """
        Start a PUG.

        See `[p]help pug` for more info.
        """
        category = category or ctx.channel.category
        if not category:
            return await ctx.send_help()
        lobby_role = await ctx.guild.create_role(
            name=f"{category.name} PUG", colour=discord.Colour.red()
        )
        lobby = Lobby(role=lobby_role, category=category)
        self.lobbies[category.id] = lobby
        all_guild = await self.config.guild(ctx.guild).all()
        if all_guild["team_text"]:
            await lobby.create_text_channel(category=lobby.category)
        if all_guild["team_voice"]:
            await lobby.create_voice_channel(category=lobby.category)
        message = await ctx.send(
            f"{ctx.author.display_name} has opened a PUG!\n"
            f"React below or use `{ctx.clean_prefix}{self.join.qualified_name}` to join!"
        )
        self.react_to_join[message.id] = lobby
        try:
            await message.add_reaction("\N{WHITE HEAVY CHECK MARK}")
        except Exception:
            pass

    @pug.command()
    @commands.guild_only()
    @pug_check(running=True)
    async def join(self, ctx: commands.Context):
        """
        Join an ongoing PUG.
        """
        lobby = self.lobbies[ctx.channel.category_id]
        await self._join(lobby, ctx.author, ctx)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.abc.User):
        if user.bot:
            return
        if not await self.bot.allowed_by_whitelist_blacklist(user):
            return
        lobby = self.react_to_join.get(reaction.message.id, None)
        if lobby is None:
            return
        await self._join(lobby, user, user)

    @staticmethod
    async def _join(lobby: Lobby, user: discord.abc.User, destination: discord.abc.Messageable):
        try:
            await lobby.add_members(user)
        except TeamIsFull:
            return await destination.send("Sorry, all teams are full.")
        if lobby.text:
            await lobby.text.send(f"Welcome to the lobby, {user.mention}!")
        else:
            await destination.send("Welcome to the lobby!")

    @pug.command()
    @checks.mod_or_permissions(manage_roles=True)
    @pug_check(running=True)
    async def split(self, ctx: commands.Context, team_size: int):
        """
        Split a staging PUG into teams.

        See `[p]help pug` for more info.
        """
        settings = await self.config.guild(ctx.guild).all()
        await self.lobbies[ctx.channel.category_id].assign_teams(
            size=team_size, create_text=settings["team_text"], create_voice=settings["team_voice"],
        )

    @pug.command()
    @checks.mod_or_permissions(manage_roles=True)
    @pug_check(running=True)
    async def stop(self, ctx: commands.Context):
        """
        Stop an ongoing PUG and clean up the category.

        See `[p]help pug` for more info.
        """
        lobby = self.lobbies.pop(ctx.channel.category_id)
        for m, l in self.react_to_join.copy().items():
            if l == lobby:
                self.react_to_join.pop(m)
                if message := discord.utils.get(ctx.bot.cached_messages, id=m):
                    await message.delete()
        archive = ctx.bot.get_channel(await self.config.guild(ctx.guild).archive())
        await lobby.teardown(archive=archive)

    @commands.group()
    @checks.admin_or_permissions(manage_channels=True)
    async def pugset(self, ctx: commands.Context):
        """
        Manage various settings for PUGs.
        """

    @pugset.command()
    @checks.admin_or_permissions(manage_channels=True)
    async def text(self, ctx: commands.Context, *, on_or_off: bool = None):
        """
        Set whether a text channel will be automatically created for PUG teams.
        """
        if on_or_off is None:
            on_or_off = not await self.config.guild(ctx.guild).team_text()
        await self.config.guild(ctx.guild).team_text.set(on_or_off)
        await ctx.send(
            "Text channels will {} be created for teams and lobbies.".format(
                "now" if on_or_off else "no longer"
            )
        )

    @pugset.command()
    @checks.admin_or_permissions(manage_channels=True)
    async def voice(self, ctx: commands.Context, *, on_or_off: bool = None):
        """
        Set whether a voice channel will be automatically created for PUG teams.

        Members in the staging voice channel will be automatically moved into
        their assigned team VC when the PUG is split into teams.
        """
        if on_or_off is None:
            on_or_off = not await self.config.guild(ctx.guild).team_voice()
        await self.config.guild(ctx.guild).team_voice.set(on_or_off)
        await ctx.send(
            "Voice channels will {} be created for teams and lobbies.".format(
                "now" if on_or_off else "no longer"
            )
        )

    @pugset.command()
    @checks.admin_or_permissions(manage_channels=True)
    async def archive(self, ctx: commands.Context, *, channel: Union[discord.TextChannel, bool]):
        """
        Sets (or unsets) the archive channel for logging PUG text channels before they are deleted.

        Use `[p]pugset archive off` to turn off archival.
        """
        if not channel:
            await self.config.guild(ctx.guild).archive.clear()
            await ctx.send("Archive unset.")
        elif channel is True:
            archive = ctx.bot.get_channel(await self.config.guild(ctx.guild).archive())
            await ctx.send(
                "Archive channel is currently {}.".format(
                    archive.mention if archive else "not set"
                )
            )
        else:
            assert isinstance(channel, discord.TextChannel)
            await self.config.guild(ctx.guild).archive.set(channel.id)
            await ctx.tick()
