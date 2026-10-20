# LuxOS - spolecne aliasy pro bash a zsh

if command -v eza &>/dev/null; then
    alias ls='eza --group-directories-first --icons=auto'
    alias ll='eza -lh --group-directories-first --icons=auto --git'
    alias la='eza -lha --group-directories-first --icons=auto --git'
    alias lt='eza --tree --level=2 --icons=auto'
else
    alias ls='ls --color=auto'
    alias ll='ls -lh --color=auto'
    alias la='ls -lha --color=auto'
fi

command -v bat &>/dev/null && alias cat='bat --paging=never --style=plain'
alias grep='grep --color=auto'
alias diff='diff --color=auto'
alias ip='ip -color=auto'
alias df='df -h'
alias du='du -h'
alias free='free -h'
alias ..='cd ..'
alias ...='cd ../..'
alias ....='cd ../../..'

# macOS zvyklosti
alias open='xdg-open'
alias pbcopy='xclip -selection clipboard'
alias pbpaste='xclip -selection clipboard -o'

# Sprava systemu pres lux
alias update='lux update'
alias install='lux install'
alias search='lux search'

export EDITOR="${EDITOR:-nano}"
export VISUAL="${VISUAL:-$EDITOR}"
export PAGER="${PAGER:-less}"
export LESS='-R -F -i'
export MANPAGER="sh -c 'col -bx | bat -l man -p'"
export MANROFFOPT='-c'
export BAT_THEME="${BAT_THEME:-ansi}"
