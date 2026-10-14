"""Command-line admin for when nobody can sign in (or inside Docker).
  python -m app.admin create-admin <username> "<Full Name>"      (prompts for password)
  python -m app.admin reset-password <username>                     (prompts for password)
  python -m app.admin list"""
import sys, getpass
from . import auth
def main(a):
    if not a or a[0] not in ("create-admin", "reset-password", "list"): print(__doc__); return 1
    if a[0] == "list":
        for u in auth.list_users(): print(u["username"], u["role"], "active" if u["active"] else "inactive", u["display"]); return 0
    pw = getpass.getpass("New password (10+ characters): ")
    if pw != getpass.getpass("Repeat: "): print("Passwords differ."); return 1
    if a[0] == "create-admin":
        auth.create_user(a[1], a[2] if len(a) > 2 else a[1], pw, "admin"); print("Admin created.")
    else:
        with auth.db() as c:
            n = c.execute("UPDATE users SET pw=?, active=1, must_change=0 WHERE username=?", (auth.hash_pw(pw), a[1].lower())).rowcount
        print("Password reset." if n else "No such user."); auth.alog(a[1], "password reset via command line")
    return 0
if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
