from babel import dates
from redbot.core.i18n import get_babel_locale


MAX_FILE = 8_000_000


def _message_format(message, last_message):
    final = []
    if not last_message:
        final.append(dates.format_date(message.created_at.date(), locale=get_babel_locale()))
    elif message.created_at.date() != last_message.created_at.date():
        final.extend(("", dates.format_date(message.created_at.date(), locale=get_babel_locale())))
    if message.author.bot:
        author = f"BOT {message.author.display_name}"
    else:
        author = message.author.display_name
    if message.edited_at:
        if message.edited_at.date() == message.created_at.date():
            post = f" (edited {dates.format_time(message.edited_at.time(), locale=get_babel_locale())})"
        else:
            post = (
                f" (edited {dates.formate_datetime(message.edited_at, locale=get_babel_locale())})"
            )
    else:
        post = ""
    final.append(
        f"[{dates.format_time(message.created_at.time(), locale=get_babel_locale())}] "
        f"{author}: {message.clean_content}{post}"
    )
    final.extend(attachment.url for attachment in message.attachments)
    return (f"{line}\n".encode("utf-8") for line in final)


async def log(team, destination):
    channel = team.text
    bios = [BytesIO()]
    last_message = None
    members = set()
    async for message in channel.history(limit=None, oldest_first=True):
        bios[-1].writelines(_message_format(message, last_message))
        if bios[-1].tell() > MAX_FILE:
            bios[-1].seek(0)
            bios.append(BytesIO())
        if not message.author.bot:
            members.add(message.author)
        last_message = message
    if not last_message or not members:
        LOG.info("Nothing to log.")
        return
    bios[-1].seek(0)
    if len(bios) == 1:
        bios = [discord.File(bios[-1], filename=f"{channel}.md")]
    else:
        bios = [discord.File(bio, filename=f"{channel}_part-{i}.md") for i, bio in enumerate(bios)]
    embed = discord.Embed(
        title=str(channel).replace("-", " ").title(),
        description="\n".join(
            f"{m.display_name} ({m.id})"
            for m in sorted(members, key=lambda m: (m.top_role, -m.id), reverse=True)
        )
        or "*Nobody*",
        colour=team.role.colour,
    ).set_thumbnail(url=team.role.guild.icon_url)
    if not destination:
        destination = channel
        LOG.info("No specified archive destination for %s, logging to team channel.", team)
    await destination.send(embed=embed)
    for bio in bios:
        await destination.send(file=bio)
