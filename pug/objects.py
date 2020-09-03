import asyncio
import colorsys
import contextlib
import math
import random
from dataclasses import dataclass, field
from itertools import chain, repeat
from typing import List, Optional

import discord
from redbot.core.utils.chat_formatting import humanize_list

from .formatting import log


phi = (math.sqrt(5) - 1) / 2


class TeamError(Exception):
    pass


class TeamIsFull(Exception):
    pass


@dataclass
class Team:
    role: discord.Role
    text: Optional[discord.TextChannel] = None
    voice: Optional[discord.VoiceChannel] = None

    async def add_members(self, *members: discord.Member, welcome: Optional[bool] = None) -> None:
        await self.move(*members, from_team=None, to_team=self, welcome=welcome)

    async def remove_members(self, *members, welcome: Optional[bool] = None) -> None:
        await self.move(*members, from_team=self, to_team=None, welcome=welcome)

    @classmethod
    async def move(
        cls,
        *members: discord.Member,
        from_team: Optional["Team"] = None,
        to_team: Optional["Team"] = None,
        welcome: Optional[bool] = None,
    ):
        if not members:
            return
        if not any((from_team, to_team)):
            return
        for i, member in enumerate(members, 1):
            roles = member.roles
            in_voice = False
            if from_team:
                roles.remove(from_team.role)
                if member.voice:
                    in_voice = member.voice.channel == from_team.voice
            if to_team:
                roles.append(to_team.role)
            await member.edit(roles=roles)
            if in_voice and to_team and to_team.voice:
                await member.move_to(to_team.voice)
        if welcome is True:
            l = humanize_list(list(map(lambda m: m.mention, members)))
        elif welcome is None:
            l = humanize_list(list(map(str, members)))
        elif welcome is False:
            return
        if from_team and from_team.text:
            await from_team.text.send(f"Goodbye, {l}!")
        if to_team and to_team.text:
            await to_team.text.send(f"Welcome to the {cls.__name__.lower()}, {l}!")

    def _get_overs(self, overs: dict = None) -> dict:
        overs = overs or {}
        overs.setdefault(self.role, discord.PermissionOverwrite()).update(
            read_messages=True, send_messages=True, connect=True
        )
        overs.setdefault(self.role.guild.me, discord.PermissionOverwrite()).update(
            read_messages=True, send_messages=True, connect=True
        )
        overs.setdefault(self.role.guild.default_role, discord.PermissionOverwrite()).update(
            read_messages=False
        )
        return overs

    async def create_text_channel(
        self, *, name: Optional[str] = None, category: Optional[discord.CategoryChannel] = None
    ) -> discord.TextChannel:
        if self.text:
            return self.text
        overs = category.overwrites if category else None
        self.text = await self.role.guild.create_text_channel(
            name=name if name else self.role.name,
            overwrites=self._get_overs(overs),
            category=category,
        )
        return self.text

    async def create_voice_channel(
        self, *, name: Optional[str] = None, category: Optional[discord.CategoryChannel] = None
    ) -> discord.VoiceChannel:
        if self.voice:
            return self.voice
        overs = category.overwrites if category else None
        self.voice = await self.role.guild.create_voice_channel(
            name=name if name else self.role.name,
            overwrites=self._get_overs(overs),
            category=category,
        )
        return self.voice

    async def teardown(self, *, archive: Optional[discord.TextChannel] = None) -> None:
        if self.text:
            if archive:
                await log(self, archive)
            await self.text.delete(reason="PUG has ended.")
        if self.voice:
            await self.voice.delete(reason="PUG has ended.")
        if self.role:
            await self.role.delete(reason="PUG has ended.")

    @property
    def members(self) -> List[discord.Member]:
        return self.role.members

    def __bool__(self) -> bool:
        # don't call __len__ implicitly
        return True

    def __len__(self) -> int:
        return len(self.role.members)

    def __contains__(self, item) -> bool:
        return item in self.role.members


@dataclass
class Lobby(Team):
    category: discord.CategoryChannel = None
    teams: List["Team"] = field(init=False, default_factory=list)

    def __post_init__(self):
        if not self.category:
            raise TypeError()

    async def add_members(self, *members: discord.Member, welcome: Optional[bool] = None) -> None:
        # find first team that isn't full-size
        if self.teams:
            full = len(self.teams[0])
            first_index = next((i for i, team in enumerate(self.teams) if len(team) < full), -1)
            if first_index == -1:
                raise TeamIsFull()
            if first_index + len(members) > len(self.teams):
                raise TeamIsFull()
            for i, member in enumerate(members):
                await self.teams[first_index + i].add_members(member, welcome=welcome)
        else:
            await super().add_members(*members, welcome=welcome)

    async def assign_teams(
        self,
        *,
        size: int = 0,
        count: int = 0,
        prefix="Team ",
        create_text: bool = False,
        create_voice: bool = False,
    ) -> None:
        if self.teams:
            raise TeamError("Members have already been assigned.")
        if bool(size) == bool(count):
            raise TeamError("Must specify exactly one of either size or count arguments.")
        num_staging = len(self)
        if not num_staging:
            raise TeamError("Nobody to assign")
        if count:
            size = math.ceil(num_staging / count)
        full, partial = divmod(num_staging, size)
        if partial:
            partial = size - partial
            full -= partial
        num_teams = full + partial
        sampled = random.sample(self.members, num_staging)
        for i, s in enumerate(chain(repeat(size, full), repeat(size - 1, partial)), 1):
            members, sampled = sampled[:s], sampled[s:]
            colour = discord.Colour.from_hsv(i * phi, 1, 1)
            team_role = await self.category.guild.create_role(name=f"{prefix} {i}", colour=colour)
            team = Team(team_role)
            self.teams.append(team)
            if create_text:
                await team.create_text_channel(category=self.category)
            if create_voice:
                await team.create_voice_channel(category=self.category)
            await self.move(*members, from_team=self, to_team=team)
        if self.text:
            overs = self.text.overwrites
            overs.update(dict.fromkeys((t.role for t in self.teams), overs[self.role]))
            await self.text.edit(overwrites=overs)

    async def teardown(self, *, archive: Optional[discord.TextChannel] = None) -> None:
        for team in self.teams:
            await team.teardown(archive=archive)
        await super().teardown(archive=archive)
