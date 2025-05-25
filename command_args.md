# Command Arguments
```python
Seg.type = "command"
```
## 群聊禁言
```python
Seg.data: Dict[str, Any] = {
    "name": "GROUP_BAN"
    "args": {
        "qq_id": "用户QQ号",
        "duration": "禁言时长（秒）"
    },
}
```
其中，群聊ID将会通过Group_Info.group_id自动获取。
## 群聊全体禁言
```python
Seg.data: Dict[str, Any] = {
    "name": "GROUP_WHOLE_BAN"
    "args": {
        "enable": "是否开启全体禁言（True/False）"
    },
}
```
其中，群聊ID将会通过Group_Info.group_id自动获取。

`enable`的参数需要为boolean类型，True表示开启全体禁言，False表示关闭全体禁言。
## 群聊踢人
```python
Seg.data: Dict[str, Any] = {
    "name": "GROUP_KICK"
    "args": {
        "qq_id": "用户QQ号",
    },
}
```
其中，群聊ID将会通过Group_Info.group_id自动获取。